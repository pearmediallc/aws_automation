from flask import Flask, request, jsonify, render_template, send_from_directory, send_file, session
from flask_cors import CORS
import threading
import uuid
import os
import re
import io
import boto3
from bs4 import BeautifulSoup
from config import Config
from aws_automation import AWSAutomation
from flask_login import LoginManager, login_required, UserMixin, login_user, logout_user, current_user
from flask import redirect, url_for
from datetime import timedelta
import requests
import shutil
import time
import mimetypes
import hashlib
from urllib.parse import urljoin, urlparse, urlunparse
import chardet
import zipfile
from w3bcopier_module import w3bcopier_bp  # Import the Blueprint
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')
if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY must be set in environment variables")
app.permanent_session_lifetime = timedelta(minutes=2)

# Register the w3bcopier Blueprint with a URL prefix
app.register_blueprint(w3bcopier_bp, url_prefix='/w3bcopier')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

CORS(app)

# Define user class
class User(UserMixin):
    def __init__(self, id, name, password):
        self.id = id
        self.name = name
        self.password = password

# Get admin credentials from environment variables (required)
username = os.getenv('ADMIN_USERNAME')
password = os.getenv('ADMIN_PASSWORD')

if not username or not password:
    raise ValueError("ADMIN_USERNAME and ADMIN_PASSWORD must be set in environment variables")

users = {
    username: User(id=username, name='Admin', password=password)
}

@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

# ===== AUTHENTICATION ROUTES =====

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username in users and password == users[username].password:
            login_user(users[username])
            session.permanent = True
            return redirect(url_for('home'))
        error = 'Invalid username or password'
    return render_template('login.html', error=error)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ===== MAIN ROUTES =====

@app.route('/')
@login_required
def home():
    return render_template('app.html')

@app.route('/w3bcopier')
@login_required
def w3bcopier():
    try:
        print("W3bCopier route accessed successfully")  # Debug log
        return render_template('web.html')
    except Exception as e:
        print(f"Error in w3bcopier route: {str(e)}")
        return f"Error loading W3bCopier: {str(e)}", 500

# Store domain setup status
domain_status = {}

# ===== W3BCOPIER SCRAPER CLASS =====

# (Class removed; now using w3bcopier_module.py)

# ===== DOMAIN SETUP FUNCTIONALITY =====

def setup_domain_async(domain, task_id, account_key='auto-insurance'):
    """Async function to setup domain"""
    automation = AWSAutomation(account_key=account_key)
    
    def update_progress(message, step_key=None, step_status=None):
        domain_status[task_id]['progress'] = message
        if step_key and step_status:
            if 'steps' not in domain_status[task_id]:
                domain_status[task_id]['steps'] = {}
            if step_key not in domain_status[task_id]['steps']:
                domain_status[task_id]['steps'][step_key] = {}
            domain_status[task_id]['steps'][step_key]['status'] = step_status
    
    result = automation.setup_domain(domain, progress_callback=update_progress)
    domain_status[task_id] = result

# ===== API ROUTES =====

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'})

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """Get available AWS accounts"""
    accounts = []
    for key, config in Config.AWS_ACCOUNTS.items():
        accounts.append({
            'key': key,
            'name': config['name'],
            'region': config['region']
        })
    return jsonify({'accounts': accounts})

@app.route('/api/check-existing/<domain>', methods=['GET'])
def check_existing_resources(domain):
    """Check for existing AWS resources for a domain"""
    automation = AWSAutomation()
    
    try:
        result = {
            'domain': domain,
            'resources': {}
        }
        
        # Check CloudFront
        cf_result = automation.check_existing_cloudfront_distribution(domain)
        result['resources']['cloudfront'] = cf_result
        
        # Check Route 53 hosted zone
        try:
            response = automation.route53_client.list_hosted_zones_by_name(DNSName=domain)
            zones = response.get('HostedZones', [])
            for zone in zones:
                if zone['Name'].rstrip('.') == domain:
                    result['resources']['route53'] = {
                        'exists': True,
                        'zone_id': zone['Id'].split('/')[-1],
                        'name': zone['Name']
                    }
                    break
            else:
                result['resources']['route53'] = {'exists': False}
        except Exception:
            result['resources']['route53'] = {'exists': False}
        
        # Check S3 buckets
        try:
            automation.s3_client.head_bucket(Bucket=domain)
            result['resources']['s3_main'] = {'exists': True}
        except:
            result['resources']['s3_main'] = {'exists': False}
        
        try:
            automation.s3_client.head_bucket(Bucket=f'www.{domain}')
            result['resources']['s3_www'] = {'exists': True}
        except:
            result['resources']['s3_www'] = {'exists': False}
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/setup-domain', methods=['POST'])
def setup_domain():
    """Endpoint to start domain setup (supports multiple domains and accounts)"""
    data = request.json
    domains_input = data.get('domain', '').strip()
    account_key = data.get('account', 'auto-insurance')
    
    if not domains_input:
        return jsonify({'error': 'Domain is required'}), 400
    
    # Validate account key
    if account_key not in Config.AWS_ACCOUNTS:
        return jsonify({'error': f'Invalid account: {account_key}'}), 400
    
    # Parse multiple domains separated by comma
    domains = [d.strip() for d in domains_input.split(',') if d.strip()]
    
    if not domains:
        return jsonify({'error': 'No valid domains provided'}), 400
    
    # Generate task IDs for each domain
    tasks = []
    
    for domain in domains:
        task_id = str(uuid.uuid4())
        
        # Initialize status
        domain_status[task_id] = {
            'domain': domain,
            'account': Config.AWS_ACCOUNTS[account_key]['name'],
            'status': 'started',
            'progress': 'Initializing...'
        }
        
        # Start async setup
        thread = threading.Thread(
            target=setup_domain_async,
            args=(domain, task_id, account_key)
        )
        thread.start()
        
        tasks.append({
            'task_id': task_id,
            'domain': domain,
            'account': Config.AWS_ACCOUNTS[account_key]['name']
        })
    
    return jsonify({
        'tasks': tasks,
        'message': f'Domain setup started for {len(domains)} domain(s) on {Config.AWS_ACCOUNTS[account_key]["name"]}'
    })

@app.route('/api/status/<task_id>', methods=['GET'])
def get_status(task_id):
    """Get status of domain setup"""
    if task_id not in domain_status:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify(domain_status[task_id])

@app.route('/api/buckets/<account_key>', methods=['GET'])
def get_buckets(account_key):
    """Get S3 buckets for the specified AWS account"""
    try:
        # Validate account key
        if account_key not in Config.AWS_ACCOUNTS:
            return jsonify({'error': f'Invalid account: {account_key}'}), 400
            
        # Get account credentials
        account_config = Config.AWS_ACCOUNTS[account_key]
        access_key_id = account_config['access_key_id']
        secret_access_key = account_config['secret_access_key']
        region = account_config['region']
        
        # Create S3 client
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        
        # List buckets
        response = s3_client.list_buckets()
        
        buckets = []
        for bucket in response['Buckets']:
            buckets.append({
                'name': bucket['Name'],
                'creation_date': bucket['CreationDate'].isoformat()
            })
        
        return jsonify({'buckets': buckets})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bucket-files/<account_key>/<bucket_name>', methods=['GET'])
def get_bucket_files(account_key, bucket_name):
    """List files in an S3 bucket"""
    try:
        # Validate account key
        if account_key not in Config.AWS_ACCOUNTS:
            return jsonify({'error': f'Invalid account: {account_key}'}), 400
            
        # Get account credentials
        account_config = Config.AWS_ACCOUNTS[account_key]
        access_key_id = account_config['access_key_id']
        secret_access_key = account_config['secret_access_key']
        region = account_config['region']
        
        # Create S3 client
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        
        # List objects in bucket
        try:
            response = s3_client.list_objects_v2(Bucket=bucket_name)
        except s3_client.exceptions.NoSuchBucket:
            return jsonify({'error': f'Bucket {bucket_name} does not exist'}), 404
        
        files = []
        if 'Contents' in response:
            for obj in response['Contents']:
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat()
                })
        
        return jsonify({
            'bucket': bucket_name,
            'files': files
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/replace-script', methods=['POST'])
def replace_script():
    """Replace script in a specific HTML file in an S3 bucket"""
    data = request.json
    account_key = data.get('account')
    bucket_name = data.get('bucket')
    file_key = data.get('file')
    find_text = data.get('find')
    replace_text = data.get('replace')
    
    if not all([account_key, bucket_name, file_key, find_text]):
        return jsonify({'error': 'Missing required parameters'}), 400
    
    try:
        # Validate account key
        if account_key not in Config.AWS_ACCOUNTS:
            return jsonify({'error': f'Invalid account: {account_key}'}), 400
            
        # Get account credentials
        account_config = Config.AWS_ACCOUNTS[account_key]
        access_key_id = account_config['access_key_id']
        secret_access_key = account_config['secret_access_key']
        region = account_config['region']
        
        # Create S3 client
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        
        # Verify the file exists
        try:
            # Get file content
            obj_response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
            content = obj_response['Body'].read().decode('utf-8')
        except s3_client.exceptions.NoSuchKey:
            return jsonify({'error': f'File {file_key} does not exist in bucket {bucket_name}'}), 404
        
        # Replace text
        if find_text in content:
            new_content = content.replace(find_text, replace_text)
            
            # Upload modified content
            s3_client.put_object(
                Bucket=bucket_name,
                Key=file_key,
                Body=new_content.encode('utf-8'),
                ContentType='text/html'
            )
            
            return jsonify({
                'message': f'Script replaced in file: {file_key}',
                'modified_file': file_key
            })
        else:
            return jsonify({'message': f'Text not found in file: {file_key}. No changes were made.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/add-script', methods=['POST'])
def add_script():
    """Add script to head or body in a specific HTML file in an S3 bucket"""
    data = request.json
    account_key = data.get('account')
    bucket_name = data.get('bucket')
    file_key = data.get('file')
    script_text = data.get('script')
    location = data.get('location', 'head')
    
    if not all([account_key, bucket_name, file_key, script_text]):
        return jsonify({'error': 'Missing required parameters'}), 400
    
    if location not in ['head', 'body']:
        return jsonify({'error': 'Invalid location. Must be "head" or "body"'}), 400
    
    try:
        # Validate account key
        if account_key not in Config.AWS_ACCOUNTS:
            return jsonify({'error': f'Invalid account: {account_key}'}), 400
            
        # Get account credentials
        account_config = Config.AWS_ACCOUNTS[account_key]
        access_key_id = account_config['access_key_id']
        secret_access_key = account_config['secret_access_key']
        region = account_config['region']
        
        # Create S3 client
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        
        # Verify the file exists
        try:
            # Get file content
            obj_response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
            content = obj_response['Body'].read().decode('utf-8')
        except s3_client.exceptions.NoSuchKey:
            return jsonify({'error': f'File {file_key} does not exist in bucket {bucket_name}'}), 404
        
        # Add script to appropriate location
        if location == 'head':
            # Check if head tag exists
            if '</head>' not in content.lower():
                return jsonify({'error': f'No closing </head> tag found in file {file_key}'}), 400
                
            # Add before closing head tag
            pattern = re.compile(r'</head>', re.IGNORECASE)
            new_content = pattern.sub(f'{script_text}\n</head>', content)
        else:  # body
            # Check if body tag exists
            if '</body>' not in content.lower():
                return jsonify({'error': f'No closing </body> tag found in file {file_key}'}), 400
                
            # Add before closing body tag
            pattern = re.compile(r'</body>', re.IGNORECASE)
            new_content = pattern.sub(f'{script_text}\n</body>', content)
        
        # Upload modified content
        s3_client.put_object(
            Bucket=bucket_name,
            Key=file_key,
            Body=new_content.encode('utf-8'),
            ContentType='text/html'
        )
        
        return jsonify({
            'message': f'Script added to {location} in file: {file_key}',
            'modified_file': file_key
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bucket-contents/<account_key>/<bucket_name>')
def get_bucket_contents(account_key, bucket_name):
    """Get contents of an S3 bucket with support for nested folders"""
    try:
        # Validate account key
        if account_key not in Config.AWS_ACCOUNTS:
            return jsonify({'error': f'Invalid account: {account_key}'}), 400
            
        # Get account credentials
        account_config = Config.AWS_ACCOUNTS[account_key]
        access_key_id = account_config['access_key_id']
        secret_access_key = account_config['secret_access_key']
        region = account_config['region']
        
        # Create S3 client
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        
        # Get prefix from query parameters
        prefix = request.args.get('prefix', '')
        # Check if we want all contents (no delimiter) or just immediate contents
        all_contents = request.args.get('all', 'false').lower() == 'true'
        
        # List objects in bucket with prefix
        try:
            if all_contents:
                # Get all objects recursively (no delimiter)
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=prefix
                )
            else:
                # Get only immediate contents (with delimiter)
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=prefix,
                    Delimiter='/'
                )
        except s3_client.exceptions.NoSuchBucket:
            return jsonify({'error': f'Bucket {bucket_name} does not exist'}), 404
        
        contents = []
        
        # Add common prefixes (folders)
        if 'CommonPrefixes' in response:
            for prefix in response['CommonPrefixes']:
                contents.append({
                    'key': prefix['Prefix'],
                    'type': 'folder',
                    'name': prefix['Prefix'].rstrip('/').split('/')[-1]
                })
        
        # Add objects (files)
        if 'Contents' in response:
            for obj in response['Contents']:
                # Skip the prefix itself if it's a folder
                if obj['Key'] == prefix:
                    continue
                    
                # Skip if the object is a folder (ends with /)
                if obj['Key'].endswith('/'):
                    continue
                    
                contents.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                    'type': 'file',
                    'name': obj['Key'].split('/')[-1]
                })
        
        # Sort contents: folders first, then files, both alphabetically
        contents.sort(key=lambda x: (0 if x['type'] == 'folder' else 1, x['name'].lower()))
        
        return jsonify({
            'bucket': bucket_name,
            'prefix': prefix,
            'contents': contents
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def extract_domain(bucket_name):
    """Extract domain name from bucket name."""
    parts = bucket_name.split('.')
    if len(parts) >= 2:
        return '.'.join(parts[:-1])
    return bucket_name

def replace_domain_in_content(content, source_bucket, target_bucket, source_domain, target_domain):
    """Perform two-step domain replacement in content."""
    # Step 1: Replace entire bucket name
    content = content.replace(source_bucket, target_bucket)
    
    # Step 2: Replace just the domain part
    content = content.replace(source_domain, target_domain)
    
    return content

@app.route('/api/copy-files', methods=['POST'])
def copy_files():
    try:
        data = request.json
        source_account = data.get('sourceAccount')
        source_bucket = data.get('sourceBucket')
        target_account = data.get('targetAccount')
        target_bucket = data.get('targetBucket')
        selected_folders = data.get('selectedFolders', [])
        selected_files = data.get('selectedFiles', [])
        
        # Get search and replace terms if enabled
        enable_search_replace = data.get('enableSearchReplace', False)
        search_terms = []
        replace_terms = []
        
        if enable_search_replace:
            search_terms = [term.strip() for term in data.get('searchTerms', '').split(',') if term.strip()]
            replace_terms = [term.strip() for term in data.get('replaceTerms', '').split(',') if term.strip()]
            
            if len(search_terms) != len(replace_terms):
                return jsonify({'error': 'Number of search terms must match number of replace terms'}), 400
        
        # Extract domains using the new function
        source_domain = extract_domain(source_bucket)
        target_domain = extract_domain(target_bucket)
        
        replace_variations = data.get('replaceVariations', True)
        preserve_case = data.get('preserveCase', True)
        
        print(f"Source bucket: {source_bucket}, Target bucket: {target_bucket}")
        print(f"Source domain: {source_domain}, Target domain: {target_domain}")
        print(f"Replace variations: {replace_variations}, Preserve case: {preserve_case}")
        if enable_search_replace:
            print(f"Search terms: {search_terms}")
            print(f"Replace terms: {replace_terms}")
            print(f"Selected folders for search/replace: {selected_folders}")
        
        if not source_account or not source_bucket or not target_account or not target_bucket:
            return jsonify({'error': 'Missing required parameters'}), 400
        
        if not selected_folders and not selected_files:
            return jsonify({'error': 'No files or folders selected'}), 400
        
        if source_account not in Config.AWS_ACCOUNTS or target_account not in Config.AWS_ACCOUNTS:
            return jsonify({'error': 'Invalid account(s)'}), 400
        
        # Create S3 clients for source and target accounts
        source_config = Config.AWS_ACCOUNTS[source_account]
        source_s3 = boto3.client(
            's3',
            aws_access_key_id=source_config['access_key_id'],
            aws_secret_access_key=source_config['secret_access_key'],
            region_name=source_config['region']
        )
        
        target_config = Config.AWS_ACCOUNTS[target_account]
        target_s3 = boto3.client(
            's3',
            aws_access_key_id=target_config['access_key_id'],
            aws_secret_access_key=target_config['secret_access_key'],
            region_name=target_config['region']
        )
        
        # CHECK FOR EXISTING FOLDERS IN TARGET BUCKET
        existing_folders = []
        
        for folder in selected_folders:
            # Ensure folder ends with a forward slash for proper matching
            folder_prefix = folder.rstrip('/') + '/'
            
            try:
                # Check if any objects exist with this folder prefix in target bucket
                response = target_s3.list_objects_v2(
                    Bucket=target_bucket,
                    Prefix=folder_prefix,
                    MaxKeys=1  # We only need to know if at least one object exists
                )
                
                # If Contents exists and has at least one item, folder already exists
                if 'Contents' in response and len(response['Contents']) > 0:
                    existing_folders.append(folder.rstrip('/'))
                    
            except Exception as e:
                print(f"Error checking folder existence for {folder}: {str(e)}")
                # Continue checking other folders even if one fails
                continue
        
        # If any folders already exist, return error
        if existing_folders:
            existing_folders_str = "', '".join(existing_folders)
            return jsonify({
                'error': f"Cannot copy because the following folder(s) already exist in the target bucket: '{existing_folders_str}'. Please choose a different location or remove the existing folders first."
            }), 409  # 409 Conflict status code
        
        # Get list of files to copy
        files_to_copy = []
        
        # Add selected files
        files_to_copy.extend(selected_files)
        
        # Add files from selected folders
        for folder in selected_folders:
            # Ensure folder ends with a forward slash for proper matching
            if not folder.endswith('/'):
                folder += '/'
                
            paginator = source_s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=source_bucket, Prefix=folder):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        # Only include files that are directly in the selected folder
                        # and not in subfolders unless they are explicitly selected
                        key = obj['Key']
                        # Check if the key is directly under the selected folder (no additional slashes after the folder)
                        if key.startswith(folder):
                            remaining_path = key[len(folder):]
                            # If there are no more slashes, it's a direct file in the folder
                            # Or if there is a slash, it's a subfolder we want to include only if explicitly selected
                            if '/' not in remaining_path or any(
                                key.startswith(sel_folder) and sel_folder != folder 
                                for sel_folder in selected_folders
                                if sel_folder != folder
                            ):
                                files_to_copy.append(key)
        
        # Copy files         
        for file_key in files_to_copy:             
            try:                 
                # Get the file from source bucket                
                response = source_s3.get_object(Bucket=source_bucket, Key=file_key)                
                content_type = response.get('ContentType', 'application/octet-stream')                
                content = response['Body'].read()                                  
        
                # Check if we need to replace content in the file                
                if (file_key.endswith('.html') or file_key.endswith('.htm') or                      
                    file_key.endswith('.css') or file_key.endswith('.js') or                      
                    content_type in ['text/html', 'text/css', 'application/javascript']):                                           
                    
                    # Decode content if it's text                     
                    try:                         
                        content = content.decode('utf-8')                                                  
                        
                        # Perform domain replacement                         
                        content = replace_domain_in_content(                             
                            content,                              
                            source_bucket,                              
                            target_bucket,                             
                            source_domain,                             
                            target_domain                         
                        )                                                  
                        
                        # Perform custom search and replace if enabled                         
                        # Only apply to files in selected folders                         
                        if enable_search_replace and search_terms:                             
                            # Check if file is in one of the selected folders (FIXED)
                            is_in_selected_folder = False
                            for folder in selected_folders:
                                # Ensure folder name ends with '/' for exact matching
                                folder_path = folder.rstrip('/') + '/'
                                # Check if file starts with exact folder path OR is directly in the folder
                                if file_key.startswith(folder_path) or file_key == folder.rstrip('/'):
                                    is_in_selected_folder = True
                                    break
                                                       
                            if is_in_selected_folder:                                 
                                print(f"Applying search/replace to file: {file_key}")                                 
                                for search_term, replace_term in zip(search_terms, replace_terms):                                     
                                    content = content.replace(search_term, replace_term)                                                  
                        
                        # Encode back to bytes                         
                        content = content.encode('utf-8')                     
                    except UnicodeDecodeError:                         
                        print(f"Skipping content replacement for binary file: {file_key}")                                  
        
                # Upload to target bucket                 
                target_s3.put_object(                     
                    Bucket=target_bucket,                     
                    Key=file_key,                     
                    Body=content,                     
                    ContentType=content_type                 
                )                              
            except Exception as e:                 
                print(f"Error copying file {file_key}: {str(e)}")                 
                continue                  

        return jsonify({             
            'message': f'Successfully copied {len(files_to_copy)} files from {source_bucket} to {target_bucket}'         
        })              

    except Exception as e:         
        return jsonify({'error': str(e)}), 500
@app.route('/api/save-file-content', methods=['POST'])
def save_file_content():
    """Save content to a specific file in an S3 bucket"""
    data = request.json
    account_key = data.get('account')
    bucket_name = data.get('bucket')
    file_key = data.get('file')
    content = data.get('content')
    
    if not all([account_key, bucket_name, file_key, content]):
        return jsonify({'error': 'Missing required parameters'}), 400
    
    try:
        # Validate account key
        if account_key not in Config.AWS_ACCOUNTS:
            return jsonify({'error': f'Invalid account: {account_key}'}), 400
            
        # Get account credentials
        account_config = Config.AWS_ACCOUNTS[account_key]
        access_key_id = account_config['access_key_id']
        secret_access_key = account_config['secret_access_key']
        region = account_config['region']
        
        # Create S3 client
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        
        # Upload content to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=file_key,
            Body=content.encode('utf-8'),
            ContentType='text/html'
        )
        
        return jsonify({
            'message': f'File {file_key} saved successfully',
            'modified_file': file_key
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-file-content/<account_key>/<bucket_name>/<path:file_key>', methods=['GET'])
def get_file_content(account_key, bucket_name, file_key):
    """Get content of a specific file from an S3 bucket"""
    try:
        # Validate account key
        if account_key not in Config.AWS_ACCOUNTS:
            return jsonify({'error': f'Invalid account: {account_key}'}), 400
            
        # Get account credentials
        account_config = Config.AWS_ACCOUNTS[account_key]
        access_key_id = account_config['access_key_id']
        secret_access_key = account_config['secret_access_key']
        region = account_config['region']
        
        # Create S3 client
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        
        # Get file content
        try:
            response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
            content = response['Body'].read().decode('utf-8')
            
            return jsonify({
                'content': content,
                'file': file_key
            })
        except s3_client.exceptions.NoSuchKey:
            return jsonify({'error': f'File {file_key} does not exist in bucket {bucket_name}'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# The health check is now handled by the w3bcopier Blueprint at /w3bcopier/health

# ===== MAIN =====

if __name__ == '__main__':
    print("Starting AWS Automation Suite with W3bCopier...")
    print("Routes available:")
    print("  - / (Main Dashboard)")
    print("  - /w3bcopier (Website Scraper)")
    print("  - /login (Authentication)")
    app.run(debug=True, host='0.0.0.0', port=5000)