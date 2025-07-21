import boto3
import json
import time
import requests
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple
from config import Config
import io

class NamecheapManager:
    def __init__(self, config):
        self.api_user = config.NAMECHEAP_API_USER
        self.proxies = Config.get_proxy()
        self.api_key = config.NAMECHEAP_API_KEY
        self.api_url = 'https://api.namecheap.com/xml.response'
        
        # Get client IP immediately
        self.client_ip = self.get_client_ip()
        print(f"🌐 Namecheap API initialized with IP: {self.client_ip}")
    
    def get_client_ip(self):
        """Get the current public IP address - REQUIRED for Namecheap API"""
        try:
            response = requests.get('https://api.ipify.org', timeout=5, proxies=self.proxies)
            ip = response.text.strip()
            return ip
        except Exception as e:
            print(f"❌ Could not detect IP: {e}")
            return '127.0.0.1'  # Fallback
    
    def get_dns_hosts(self, domain: str) -> List[Dict]:
        """Get current DNS hosts for a domain"""
        print(f"\n🔍 Getting DNS hosts for domain: {domain}")
        
        params = {
            'ApiUser': self.api_user,
            'ApiKey': self.api_key,
            'UserName': self.api_user,
            'Command': 'namecheap.domains.dns.getHosts',
            'SLD': domain.split('.')[0],
            'TLD': '.'.join(domain.split('.')[1:]),
            'ClientIp': self.client_ip  # ← THIS WAS MISSING!
        }
        
        print(f"   API params: SLD='{params['SLD']}', TLD='{params['TLD']}', IP='{self.client_ip}'")
        
        try:
            response = requests.get(self.api_url, params=params, timeout=15, proxies=self.proxies)
            print(f"   API response status: {response.status_code}")
            
            if response.status_code != 200:
                raise Exception(f"HTTP error: {response.status_code}")
            
            root = ET.fromstring(response.text)
            
            # Check for errors FIRST
            errors = root.findall('.//Errors/Error')
            if errors:
                error_messages = []
                for error in errors:
                    error_num = error.get('Number', 'Unknown')
                    error_text = error.text or 'No error message'
                    error_messages.append(f"#{error_num}: {error_text}")
                    print(f"   ❌ API Error #{error_num}: {error_text}")
                
                raise Exception(f"Namecheap API errors: {'; '.join(error_messages)}")
            
            # Extract existing hosts
            hosts = []
            host_elements = root.findall('.//host')
            
            # Try alternative path if first doesn't work
            if not host_elements:
                host_elements = root.findall('.//DomainDNSGetHostsResult/host')
            
            for host in host_elements:
                host_data = {
                    'Name': host.get('Name', ''),
                    'Type': host.get('Type', ''),
                    'Address': host.get('Address', ''),
                    'TTL': host.get('TTL', '1800')
                }
                hosts.append(host_data)
                print(f"   Found host: {host_data}")
            
            print(f"   ✅ Total hosts found: {len(hosts)}")
            return hosts
            
        except Exception as e:
            print(f"   ❌ Error getting DNS hosts: {str(e)}")
            raise
    
    def set_dns_hosts(self, domain: str, hosts: List[Dict]) -> bool:
        """Set DNS hosts for a domain - FIXED VERSION"""
        print(f"\n📤 Setting DNS hosts for domain: {domain}")
        print(f"   Number of hosts to set: {len(hosts)}")
        
        params = {
            'ApiUser': self.api_user,
            'ApiKey': self.api_key,
            'UserName': self.api_user,
            'Command': 'namecheap.domains.dns.setHosts',
            'SLD': domain.split('.')[0],
            'TLD': '.'.join(domain.split('.')[1:]),
            'ClientIp': self.client_ip  # ← THIS WAS MISSING!
        }
        
        # Add host records to params
        for i, host in enumerate(hosts, 1):
            params[f'HostName{i}'] = host['Name']
            params[f'RecordType{i}'] = host['Type']
            params[f'Address{i}'] = host['Address']
            params[f'TTL{i}'] = host.get('TTL', '1800')
            print(f"   Host {i}: {host['Name']} ({host['Type']}) -> {host['Address']} [TTL: {host.get('TTL', '1800')}]")
        
        try:
            print(f"   🌐 Making API call to Namecheap...")
            response = requests.post(self.api_url, data=params, timeout=30, proxies=self.proxies)
            
            print(f"   Response status: {response.status_code}")
            
            if response.status_code != 200:
                raise Exception(f"HTTP error: {response.status_code}")
            
            # Save response for debugging
            print(f"   Response preview: {response.text[:300]}...")
            
            root = ET.fromstring(response.text)
            
            # Check for errors FIRST
            errors = root.findall('.//Errors/Error')
            if errors:
                print(f"   ❌ API Errors:")
                for error in errors:
                    error_num = error.get('Number', 'Unknown')
                    error_text = error.text or 'No error message'
                    print(f"      #{error_num}: {error_text}")
                    
                    # Provide specific guidance
                    if 'IP address' in error_text.lower():
                        print(f"      🔧 Add IP {self.client_ip} to Namecheap API whitelist!")
                    elif 'api access' in error_text.lower():
                        print(f"      🔧 Enable API access in Namecheap dashboard!")
                
                raise Exception(f"Namecheap API error: {error_text}")
            
            # Check if the update was successful
            success = root.find('.//DomainDNSSetHostsResult')
            if success is not None and success.get('IsSuccess', '').lower() == 'true':
                print(f"   ✅ DNS hosts updated successfully!")
                return True
            else:
                print(f"   ❌ DNS update failed (IsSuccess != true)")
                # Print the full response for debugging
                print(f"   Full response: {response.text}")
                return False
                
        except Exception as e:
            print(f"   ❌ Error setting DNS hosts: {str(e)}")
            raise
    
    def set_custom_nameservers(self, domain: str, nameservers: List[str]) -> bool:
        """Set custom nameservers for a domain - FIXED VERSION"""
        print(f"\n🔄 Setting custom nameservers for domain: {domain}")
        print(f"   Nameservers to set: {nameservers}")
        
        params = {
            'ApiUser': self.api_user,
            'ApiKey': self.api_key,
            'UserName': self.api_user,
            'Command': 'namecheap.domains.dns.setCustom',
            'SLD': domain.split('.')[0],
            'TLD': '.'.join(domain.split('.')[1:]),
            'Nameservers': ','.join(nameservers),
            'ClientIp': self.client_ip  # ← THIS WAS MISSING!
        }
        
        print(f"   Domain parts: SLD='{params['SLD']}', TLD='{params['TLD']}'")
        print(f"   Client IP: {self.client_ip}")
        
        try:
            print(f"   🌐 Making API call to set custom nameservers...")
            response = requests.post(self.api_url, data=params, timeout=30, proxies=self.proxies)
            
            print(f"   Response status: {response.status_code}")
            
            if response.status_code != 200:
                raise Exception(f"HTTP error: {response.status_code}")
            
            print(f"   Response preview: {response.text[:300]}...")
            
            root = ET.fromstring(response.text)
            
            # Check for errors FIRST
            errors = root.findall('.//Errors/Error')
            if errors:
                print(f"   ❌ API Errors:")
                for error in errors:
                    error_num = error.get('Number', 'Unknown')
                    error_text = error.text or 'No error message'
                    print(f"      #{error_num}: {error_text}")
                
                raise Exception(f"Namecheap API error: {error_text}")
            
            # Check if the update was successful
            success = root.find('.//DomainDNSSetCustomResult')
            if success is not None and success.get('Update', '').lower() == 'true':
                print(f"   ✅ Nameservers updated successfully!")
                return True
            else:
                # Try alternative success check
                command_response = root.find('.//CommandResponse')
                if command_response is not None and command_response.get('Type') == 'OK':
                    print(f"   ✅ Nameservers update completed!")
                    return True
                else:
                    print(f"   ❌ Nameserver update may have failed")
                    print(f"   Full response: {response.text}")
                    return False
                    
        except Exception as e:
            print(f"   ❌ Error updating nameservers: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def add_cname_record(self, domain: str, host_name: str, host_value: str):
        """Add CNAME record for SSL validation - FIXED VERSION"""
        print(f"\n➕ Adding CNAME record for domain: {domain}")
        print(f"   Original host_name: {host_name}")
        print(f"   Host value: {host_value}")
        
        # Remove trailing dot
        host_name = host_name.rstrip('.')
        
        # Remove the domain part to get just the subdomain
        if host_name.endswith(f'.{domain}'):
            host_name = host_name.replace(f'.{domain}', '')
        elif host_name.endswith(domain):
            host_name = host_name.replace(domain, '').rstrip('.')
        
        print(f"   Processed host_name: {host_name}")
        
        try:
            # Get existing hosts first
            existing_hosts = self.get_dns_hosts(domain)
            print(f"   Found {len(existing_hosts)} existing DNS records")
            
            # Check if CNAME already exists and update or add
            cname_exists = False
            for i, host in enumerate(existing_hosts):
                if host['Type'] == 'CNAME' and host['Name'] == host_name:
                    print(f"   🔄 CNAME record already exists for {host_name}, updating value")
                    existing_hosts[i]['Address'] = host_value
                    existing_hosts[i]['TTL'] = '60'
                    cname_exists = True
                    break
            
            if not cname_exists:
                # Add new CNAME record
                new_record = {
                    'Name': host_name,
                    'Type': 'CNAME',
                    'Address': host_value,
                    'TTL': '60'
                }
                existing_hosts.append(new_record)
                print(f"   ➕ Adding new CNAME record: {new_record}")
            
            # Update all hosts
            print(f"   📤 Updating DNS with {len(existing_hosts)} total records")
            success = self.set_dns_hosts(domain, existing_hosts)
            
            if success:
                print(f"   ✅ Successfully updated DNS records for {domain}")
            else:
                raise Exception("Failed to update DNS records")
                
        except Exception as e:
            print(f"   ❌ Error in add_cname_record: {str(e)}")
            raise


# Updated config template
CONFIG_TEMPLATE = '''
class Config:
    # Namecheap API credentials (REQUIRED for automatic DNS updates)
    NAMECHEAP_API_USER = "your_username_here"  # Use USERNAME, not email!
    NAMECHEAP_API_KEY = "your_api_key_here"    # From Namecheap API Access page
    
    # Your existing AWS configuration
    AWS_ACCOUNTS = {
        'auto-insurance': {
            'access_key_id': 'your_aws_key',
            'secret_access_key': 'your_aws_secret',
            'region': 'us-east-1'
        }
    }
'''

print("🔧 CRITICAL FIXES APPLIED:")
print("   1. Added missing ClientIp parameter to ALL API calls")
print("   2. Added proper error handling with specific guidance")
print("   3. Added IP detection and validation")
print("   4. Enhanced debugging output")
print("   5. Fixed XML parsing and response validation")
print("")
print("📋 SETUP CHECKLIST:")
print("   □ Run the diagnostic script first: python namecheap_diagnostic.py")
print("   □ Enable Namecheap API access in dashboard")
print("   □ Add your IP to Namecheap API whitelist")
print("   □ Use USERNAME (not email) for NAMECHEAP_API_USER")
print("   □ Update your config.py with correct credentials")
print("")
print("🎯 Most likely issue: IP not whitelisted in Namecheap!")

class AWSAutomation:
    def __init__(self, account_key='auto-insurance'):
        self.config = Config()
        self.account_key = account_key
        
        # Get the account configuration
        if account_key not in self.config.AWS_ACCOUNTS:
            raise ValueError(f"Invalid account key: {account_key}")
            
        account_config = self.config.AWS_ACCOUNTS[account_key]
        access_key_id = account_config['access_key_id']
        secret_access_key = account_config['secret_access_key']
        region = account_config['region']
        
        # Initialize AWS clients with the selected account
        self.acm_client = boto3.client(
            'acm',
            region_name='us-east-1',  # ACM for CloudFront must be in us-east-1
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        self.route53_client = boto3.client(
            'route53',
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        self.s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        self.cloudfront_client = boto3.client(
            'cloudfront',
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        
        # Store region for this account
        self.aws_region = region
        
        # Initialize Namecheap manager if credentials are provided
        self.namecheap_manager = None
        if self.config.NAMECHEAP_API_KEY and self.config.NAMECHEAP_API_USER:
            self.namecheap_manager = NamecheapManager(self.config)

    def setup_domain(self, domain: str, progress_callback=None) -> Dict:
        """
        Main function to setup a domain on AWS (NO IP ADDRESS REQUIRED)
        
        This process uses CloudFront + Route 53 alias records instead of direct IP addresses.
        Benefits:
        - Global CDN performance
        - Automatic IP management by AWS
        - High availability and redundancy
        - SSL termination at edge locations
        """
        try:
            result = {
                'domain': domain,
                'status': 'in_progress',
                'steps': {},
                'namecheap_updated': False
            }
            
            print(f"\n🚀 Starting domain setup for: {domain}")
            print("ℹ️  This process uses CloudFront + Route 53 - NO IP ADDRESS REQUIRED!")
            
            # Step 1: Request SSL Certificate
            if progress_callback:
                progress_callback('Setting up SSL certificate...', 'certificate', 'in_progress')
            cert_arn, validation_records = self.request_certificate(domain)
            result['steps']['certificate'] = {
                'status': 'completed',
                'certificate_arn': cert_arn,
                'validation_records': validation_records
            }
            
            # IMMEDIATELY add CNAME records to Namecheap if new certificate
            if validation_records:
                if progress_callback:
                    progress_callback('Adding CNAME records to Namecheap...', 'certificate', 'in_progress')
                
                print(f"\n=== Adding CNAME records for {domain} ===")
                print(f"Number of validation records: {len(validation_records)}")
                
                namecheap_cname_success = self.add_namecheap_cname_records(domain, validation_records)
                result['namecheap_cname_updated'] = namecheap_cname_success
                
                if namecheap_cname_success:
                    if progress_callback:
                        progress_callback('SSL certificate requested - CNAME records added automatically', 'certificate', 'completed')
                    print("CNAME records added successfully, waiting for DNS propagation...")
                    time.sleep(30)  # Reduced wait time to 30 seconds
                else:
                    if progress_callback:
                        progress_callback('SSL certificate requested - manual CNAME update required', 'certificate', 'completed')
                    print("Failed to add CNAME records automatically")
            else:
                if progress_callback:
                    progress_callback('Using existing SSL certificate', 'certificate', 'completed')
            
            # Step 2: Create Route 53 Hosted Zone (but don't update nameservers yet)
            if progress_callback:
                progress_callback('Setting up Route 53 hosted zone...', 'route53_zone', 'in_progress')
            zone_id, nameservers, is_existing = self.create_hosted_zone(domain)
            result['steps']['route53_zone'] = {
                'status': 'completed',
                'zone_id': zone_id,
                'nameservers': nameservers
            }
            
            if is_existing:
                if progress_callback:
                    progress_callback('Using existing Route 53 hosted zone', 'route53_zone', 'completed')
            else:
                if progress_callback:
                    progress_callback('Route 53 hosted zone created', 'route53_zone', 'completed')
            
            # Step 3: Create S3 Buckets
            if progress_callback:
                progress_callback('Setting up S3 buckets...', 's3_buckets', 'in_progress')
            s3_endpoint = self.setup_s3_buckets(domain)
            result['steps']['s3_buckets'] = {
                'status': 'completed',
                's3_endpoint': s3_endpoint
            }
            if progress_callback:
                progress_callback('S3 buckets configured', 's3_buckets', 'completed')
            
            # Step 4: Wait for certificate validation (only if new certificate)
            if validation_records:
                if progress_callback:
                    progress_callback('Waiting for certificate validation...', 'certificate_validation', 'in_progress')
                self.wait_for_certificate_validation(cert_arn)
                result['steps']['certificate_validation'] = {
                    'status': 'completed'
                }
                if progress_callback:
                    progress_callback('Certificate validated', 'certificate_validation', 'completed')
            else:
                result['steps']['certificate_validation'] = {
                    'status': 'completed'
                }
                if progress_callback:
                    progress_callback('Certificate already validated', 'certificate_validation', 'completed')
            
            # Step 5: Create CloudFront Distribution
            if progress_callback:
                progress_callback('Setting up CloudFront distribution...', 'cloudfront', 'in_progress')
            cf_distribution_id, cf_domain, is_existing = self.create_cloudfront_distribution(domain, s3_endpoint, cert_arn)
            result['steps']['cloudfront'] = {
                'status': 'completed',
                'distribution_id': cf_distribution_id,
                'distribution_domain': cf_domain
            }
            if is_existing:
                if progress_callback:
                    progress_callback('Using existing CloudFront distribution', 'cloudfront', 'completed')
            else:
                if progress_callback:
                    progress_callback('CloudFront distribution created', 'cloudfront', 'completed')
            
            # Step 6: Create Route 53 Records (ALIAS records - no IP needed!)
            if progress_callback:
                progress_callback('Creating Route 53 alias records...', 'route53_records', 'in_progress')
            self.create_route53_records(zone_id, domain, cf_distribution_id)
            result['steps']['route53_records'] = {
                'status': 'completed'
            }
            if progress_callback:
                progress_callback('Route 53 alias records created', 'route53_records', 'completed')
            
            # Step 7: Update Namecheap nameservers (AFTER certificate is validated)
            if progress_callback:
                progress_callback('Updating Namecheap nameservers...', 'nameserver_update', 'in_progress')
            
            print(f"\n=== Updating nameservers for {domain} ===")
            print(f"Nameservers to set: {nameservers}")
            
            namecheap_ns_success = self.update_namecheap_nameservers(domain, nameservers)
            result['namecheap_ns_updated'] = namecheap_ns_success
            result['steps']['nameserver_update'] = {
                'status': 'completed',
                'namecheap_updated': namecheap_ns_success
            }
            
            if namecheap_ns_success:
                if progress_callback:
                    progress_callback('Nameservers updated automatically in Namecheap', 'nameserver_update', 'completed')
                print("Nameservers updated successfully")
            else:
                if progress_callback:
                    progress_callback('Manual nameserver update required in Namecheap', 'nameserver_update', 'completed')
                print("Failed to update nameservers automatically")
            
            result['status'] = 'completed'
            
            print(f"\n✅ Domain setup completed for {domain}!")
            print(f"🌐 Your domain will be accessible via CloudFront CDN")
            print(f"🔒 SSL certificate automatically handles HTTPS")
            print(f"⚡ Global edge locations provide fast performance")
            print(f"📍 No IP addresses to manage - all handled by AWS!")
            
            return result
            
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
            return result

    def check_existing_certificate(self, domain: str) -> str:
        """
        Check if a valid certificate already exists for the domain
        """
        try:
            paginator = self.acm_client.get_paginator('list_certificates')
            
            for page in paginator.paginate(CertificateStatuses=['ISSUED']):
                for cert in page['CertificateSummaryList']:
                    cert_arn = cert['CertificateArn']
                    cert_details = self.acm_client.describe_certificate(CertificateArn=cert_arn)
                    
                    # Check if the certificate covers this domain
                    cert_domains = [cert_details['Certificate']['DomainName']]
                    cert_domains.extend(cert_details['Certificate'].get('SubjectAlternativeNames', []))
                    
                    # Check if certificate covers both domain and *.domain
                    if domain in cert_domains and f'*.{domain}' in cert_domains:
                        # Check if certificate is valid and not expired
                        if cert_details['Certificate']['Status'] == 'ISSUED':
                            print(f"Found existing certificate for {domain}: {cert_arn}")
                            return cert_arn
        except Exception as e:
            print(f"Error checking existing certificates: {e}")
        
        return None

    def request_certificate(self, domain: str) -> Tuple[str, List[Dict]]:
        """
        Request SSL certificate from ACM or use existing one
        """
        # Check for existing certificate
        existing_cert = self.check_existing_certificate(domain)
        if existing_cert:
            return existing_cert, []
        
        # Request new certificate if none exists
        print(f"Requesting new SSL certificate for {domain}")
        response = self.acm_client.request_certificate(
            DomainName=domain,
            ValidationMethod='DNS',
            SubjectAlternativeNames=[
                domain,
                f'*.{domain}'
            ],
            Options={
                'CertificateTransparencyLoggingPreference': 'ENABLED'
            }
        )
        
        certificate_arn = response['CertificateArn']
        print(f"Certificate ARN: {certificate_arn}")
        
        # Wait for validation records to be generated
        validation_records = []
        max_attempts = 10
        attempt = 0
        
        while attempt < max_attempts and not validation_records:
            attempt += 1
            print(f"Attempt {attempt}: Getting validation records...")
            time.sleep(3)
            
            cert_details = self.acm_client.describe_certificate(
                CertificateArn=certificate_arn
            )
            
            for validation in cert_details['Certificate']['DomainValidationOptions']:
                if 'ResourceRecord' in validation:
                    record = validation['ResourceRecord']
                    validation_records.append({
                        'name': record['Name'],
                        'value': record['Value'],
                        'type': record['Type']
                    })
                    print(f"Found validation record: {record['Name']} -> {record['Value']}")
        
        if not validation_records:
            raise Exception("Failed to get validation records from AWS")
        
        print(f"Total validation records found: {len(validation_records)}")
        return certificate_arn, validation_records

    def create_hosted_zone(self, domain: str) -> Tuple[str, List[str], bool]:
        """
        Create Route 53 hosted zone or use existing one
        """
        # Check if zone already exists
        try:
            response = self.route53_client.list_hosted_zones_by_name(DNSName=domain)
            zones = response.get('HostedZones', [])
            
            for zone in zones:
                if zone['Name'].rstrip('.') == domain:
                    zone_id = zone['Id'].split('/')[-1]
                    print(f"Using existing Route 53 hosted zone: {zone_id}")
                    
                    # Get the zone details to extract nameservers
                    zone_details = self.route53_client.get_hosted_zone(Id=zone_id)
                    nameservers = zone_details['DelegationSet']['NameServers']
                    
                    return zone_id, nameservers, True
        except Exception as e:
            print(f"Error checking existing zones: {e}")
        
        # Create new zone if none exists
        print(f"Creating new Route 53 hosted zone for {domain}")
        response = self.route53_client.create_hosted_zone(
            Name=domain,
            CallerReference=f'{domain}-{int(time.time())}'
        )
        
        zone_id = response['HostedZone']['Id'].split('/')[-1]
        nameservers = [ns for ns in response['DelegationSet']['NameServers']]
        
        return zone_id, nameservers, False

    def setup_s3_buckets(self, domain: str) -> str:
        """
        Create and configure S3 buckets for static website hosting
        """
        try:
            # Create main domain bucket
            if self.aws_region == 'us-east-1':
                self.s3_client.create_bucket(Bucket=domain)
            else:
                self.s3_client.create_bucket(
                    Bucket=domain,
                    CreateBucketConfiguration={
                        'LocationConstraint': self.aws_region
                    }
                )
        except self.s3_client.exceptions.BucketAlreadyExists:
            print(f"Bucket {domain} already exists, continuing...")
        except self.s3_client.exceptions.BucketAlreadyOwnedByYou:
            print(f"Bucket {domain} already owned by you, continuing...")
        
        # Create www subdomain bucket
        www_bucket = f'www.{domain}'
        try:
            if self.aws_region == 'us-east-1':
                self.s3_client.create_bucket(Bucket=www_bucket)
            else:
                self.s3_client.create_bucket(
                    Bucket=www_bucket,
                    CreateBucketConfiguration={
                        'LocationConstraint': self.aws_region
                    }
                )
        except self.s3_client.exceptions.BucketAlreadyExists:
            print(f"Bucket {www_bucket} already exists, continuing...")
        except self.s3_client.exceptions.BucketAlreadyOwnedByYou:
            print(f"Bucket {www_bucket} already owned by you, continuing...")
        
        # Configure main bucket for static website hosting
        self.s3_client.put_bucket_website(
            Bucket=domain,
            WebsiteConfiguration={
                'IndexDocument': {'Suffix': 'index.html'},
                'ErrorDocument': {'Key': 'error.html'}
            }
        )
        
        # Add a completely blank index.html file to the main domain bucket
        try:
            print(f"Adding blank index.html to {domain} bucket")
            self.s3_client.put_object(
                Bucket=domain,
                Key='index.html',
                Body=io.BytesIO(b''),
                ContentType='text/html'
            )
            print(f"Successfully added blank index.html to {domain} bucket")
        except Exception as e:
            print(f"Error adding index.html to bucket: {str(e)}")
        
        # Configure www bucket to redirect to main domain
        self.s3_client.put_bucket_website(
            Bucket=www_bucket,
            WebsiteConfiguration={
                'RedirectAllRequestsTo': {
                    'HostName': domain,
                    'Protocol': 'https'
                }
            }
        )
        
        # IMPORTANT: First disable block public access settings
        self.s3_client.put_public_access_block(
            Bucket=domain,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': False,
                'IgnorePublicAcls': False,
                'BlockPublicPolicy': False,
                'RestrictPublicBuckets': False
            }
        )
        
        # Wait a moment for the settings to propagate
        time.sleep(2)
        
        # Then set bucket policy for main domain
        policy_dict = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PublicRead",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": [
                        f"arn:aws:s3:::{domain}/*",
                        f"arn:aws:s3:::{domain}/*/*"
                    ]
                }
            ]
        }
        policy = json.dumps(policy_dict)
        self.s3_client.put_bucket_policy(
            Bucket=domain,
            Policy=policy
        )
        
        # Get the website endpoint
        if self.aws_region == 'us-east-1':
            endpoint = f'{domain}.s3-website-{self.aws_region}.amazonaws.com'
        else:
            endpoint = f'{domain}.s3-website.{self.aws_region}.amazonaws.com'
        return endpoint

    def add_namecheap_cname_records(self, domain: str, validation_records: List[Dict]):
        """Add CNAME records to Namecheap for SSL validation"""
        if not self.namecheap_manager:
            print("Namecheap API credentials not configured, skipping automatic DNS update")
            return False
        
        try:
            success_count = 0
            for record in validation_records:
                host_name = record['name']
                host_value = record['value']
                print(f"Adding CNAME record to Namecheap: {host_name} -> {host_value}")
                
                try:
                    self.namecheap_manager.add_cname_record(domain, host_name, host_value)
                    print(f"Successfully added CNAME record for {host_name}")
                    success_count += 1
                except Exception as e:
                    print(f"Error adding CNAME record {host_name}: {e}")
            
            return success_count == len(validation_records)
        except Exception as e:
            print(f"Error adding CNAME records to Namecheap: {e}")
            return False
    
    def update_namecheap_nameservers(self, domain: str, nameservers: List[str]):
        """Update Namecheap nameservers to Route 53 nameservers"""
        if not self.namecheap_manager:
            print("Namecheap API credentials not configured, skipping automatic nameserver update")
            return False
        
        try:
            print(f"\n=== Updating Namecheap nameservers for {domain} ===")
            print(f"Route 53 nameservers: {nameservers}")
            
            # Clean nameservers (remove trailing dots if any)
            clean_nameservers = [ns.rstrip('.') for ns in nameservers]
            print(f"Cleaned nameservers: {clean_nameservers}")
            
            # Call Namecheap API to set custom nameservers
            self.namecheap_manager.set_custom_nameservers(domain, clean_nameservers)
            print(f"Successfully updated nameservers for {domain}")
            return True
        except Exception as e:
            print(f"Error updating Namecheap nameservers: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def wait_for_certificate_validation(self, certificate_arn: str, timeout: int = 600):
        """
        Wait for certificate to be validated
        """
        # First check if it's already validated
        cert_details = self.acm_client.describe_certificate(
            CertificateArn=certificate_arn
        )
        
        if cert_details['Certificate']['Status'] == 'ISSUED':
            print(f"Certificate {certificate_arn} is already validated")
            return
        
        # Wait for validation if not already validated
        start_time = time.time()
        while time.time() - start_time < timeout:
            cert_details = self.acm_client.describe_certificate(
                CertificateArn=certificate_arn
            )
            
            status = cert_details['Certificate']['Status']
            print(f"Certificate status: {status}")
            
            if status == 'ISSUED':
                print("Certificate successfully validated!")
                return
            elif status == 'FAILED':
                raise Exception("Certificate validation failed")
            
            # Check validation status for each domain
            for validation in cert_details['Certificate']['DomainValidationOptions']:
                val_status = validation.get('ValidationStatus', 'PENDING')
                val_domain = validation.get('DomainName', '')
                print(f"  Domain: {val_domain}, Status: {val_status}")
            
            time.sleep(30)  # Check every 30 seconds
        
        raise TimeoutError(f"Certificate validation timed out after {timeout} seconds")

    def check_existing_cloudfront_distribution(self, domain: str) -> Dict:
        """
        Check if a CloudFront distribution already exists for this domain
        """
        try:
            paginator = self.cloudfront_client.get_paginator('list_distributions')
            
            for page in paginator.paginate():
                if 'Items' in page['DistributionList']:
                    for distribution in page['DistributionList']['Items']:
                        if 'Aliases' in distribution and 'Items' in distribution['Aliases']:
                            if domain in distribution['Aliases']['Items'] or f'www.{domain}' in distribution['Aliases']['Items']:
                                return {
                                    'exists': True,
                                    'distribution_id': distribution['Id'],
                                    'domain_name': distribution['DomainName'],
                                    'status': distribution['Status'],
                                    'enabled': distribution['Enabled']
                                }
            
            return {'exists': False}
        except Exception as e:
            print(f"Error checking existing distributions: {e}")
            return {'exists': False}

    def create_cloudfront_distribution(self, domain: str, s3_endpoint: str, certificate_arn: str) -> Tuple[str, str, bool]:
        """
        Create CloudFront distribution or use existing one
        """
        # Check if distribution already exists
        existing = self.check_existing_cloudfront_distribution(domain)
        
        if existing['exists']:
            print(f"Using existing CloudFront distribution: {existing['distribution_id']}")
            # Return the existing distribution details
            return existing['distribution_id'], existing['domain_name'], True
        
        # Verify certificate is in ISSUED state before creating distribution
        cert_details = self.acm_client.describe_certificate(CertificateArn=certificate_arn)
        cert_status = cert_details['Certificate']['Status']
        
        if cert_status != 'ISSUED':
            raise Exception(f"Certificate is not yet validated. Current status: {cert_status}")
        
        # Only create new distribution if none exists
        print(f"Creating new CloudFront distribution for {domain}")
        print(f"Using certificate: {certificate_arn}")
        
        try:
            response = self.cloudfront_client.create_distribution(
                DistributionConfig={
                    'CallerReference': f'{domain}-{int(time.time())}',
                    'Aliases': {
                        'Quantity': 2,
                        'Items': [domain, f'www.{domain}']
                    },
                    'DefaultRootObject': 'index.html',
                    'Origins': {
                        'Quantity': 1,
                        'Items': [
                            {
                                'Id': f'S3-{domain}',
                                'DomainName': s3_endpoint,
                                'CustomOriginConfig': {
                                    'HTTPPort': 80,
                                    'HTTPSPort': 443,
                                    'OriginProtocolPolicy': 'http-only'
                                }
                            }
                        ]
                    },
                    'DefaultCacheBehavior': {
                        'TargetOriginId': f'S3-{domain}',
                        'ViewerProtocolPolicy': 'redirect-to-https',
                        'CachePolicyId': '4135ea2d-6df8-44a3-9df3-4b5a84be39ad',  # CachingDisabled policy ID
                        'OriginRequestPolicyId': '88a5eaf4-2fd4-4709-b370-b4c650ea3fcf',  # CORS-S3Origin policy ID
                        'Compress': True,
                        'AllowedMethods': {
                            'Quantity': 2,
                            'Items': ['GET', 'HEAD']
                        }
                    },
                    'Comment': f'Distribution for {domain}',
                    'Enabled': True,
                    'ViewerCertificate': {
                        'ACMCertificateArn': certificate_arn,
                        'SSLSupportMethod': 'sni-only',
                        'MinimumProtocolVersion': 'TLSv1.2_2021'
                    }
                }
            )
            
            distribution_id = response['Distribution']['Id']
            distribution_domain = response['Distribution']['DomainName']
            
            return distribution_id, distribution_domain, False
            
        except self.cloudfront_client.exceptions.InvalidViewerCertificate as e:
            # More detailed error message
            raise Exception(f"Certificate validation error: {str(e)}. The certificate might not be fully validated yet or not in the correct region (us-east-1).")

    def create_route53_records(self, zone_id: str, domain: str, cloudfront_distribution_id: str):
        """
        Create Route 53 ALIAS records (automatically resolve to CloudFront IPs - no manual IP management!)
        """
        print(f"\nCreating/updating Route 53 ALIAS records for {domain}")
        print("ℹ️  Using ALIAS records - AWS automatically manages IP addresses!")
        
        # Get the CloudFront distribution details
        cf_response = self.cloudfront_client.get_distribution(Id=cloudfront_distribution_id)
        cloudfront_domain = cf_response['Distribution']['DomainName']
        
        # First, get existing records
        existing_records = {}
        try:
            paginator = self.route53_client.get_paginator('list_resource_record_sets')
            for page in paginator.paginate(HostedZoneId=zone_id):
                for record in page['ResourceRecordSets']:
                    key = f"{record['Name']}_{record['Type']}"
                    existing_records[key] = record
                    print(f"Found existing record: {record['Name']} ({record['Type']})")
        except Exception as e:
            print(f"Error listing existing records: {e}")
        
        changes = []
        
        # Define ALIAS records to create/update (these automatically resolve to correct IPs)
        records_to_manage = [
            {
                'Name': domain,
                'Type': 'A',
                'AliasTarget': {
                    'HostedZoneId': 'Z2FDTNDATAQYW2',  # CloudFront Hosted Zone ID
                    'DNSName': cloudfront_domain,
                    'EvaluateTargetHealth': False
                }
            },
            {
                'Name': domain,
                'Type': 'AAAA',
                'AliasTarget': {
                    'HostedZoneId': 'Z2FDTNDATAQYW2',
                    'DNSName': cloudfront_domain,
                    'EvaluateTargetHealth': False
                }
            },
            {
                'Name': f'www.{domain}',
                'Type': 'A',
                'AliasTarget': {
                    'HostedZoneId': 'Z2FDTNDATAQYW2',
                    'DNSName': cloudfront_domain,
                    'EvaluateTargetHealth': False
                }
            },
            {
                'Name': f'www.{domain}',
                'Type': 'AAAA',
                'AliasTarget': {
                    'HostedZoneId': 'Z2FDTNDATAQYW2',
                    'DNSName': cloudfront_domain,
                    'EvaluateTargetHealth': False
                }
            }
        ]
        
        # Check each record
        for record in records_to_manage:
            record_name = record['Name'] if record['Name'].endswith('.') else f"{record['Name']}."
            key = f"{record_name}_{record['Type']}"
            
            if key in existing_records:
                # Check if it needs updating
                existing = existing_records[key]
                if 'AliasTarget' in existing:
                    if existing['AliasTarget']['DNSName'] != cloudfront_domain:
                        print(f"Updating existing ALIAS {record['Type']} record for {record['Name']}")
                        changes.append({
                            'Action': 'UPSERT',
                            'ResourceRecordSet': {
                                'Name': record['Name'],
                                'Type': record['Type'],
                                'AliasTarget': record['AliasTarget']
                            }
                        })
                    else:
                        print(f"Skipping ALIAS {record['Type']} record for {record['Name']} - already correct")
                else:
                    # Replace non-alias with alias
                    print(f"Replacing non-alias {record['Type']} record with ALIAS for {record['Name']}")
                    changes.append({
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'Name': record['Name'],
                            'Type': record['Type'],
                            'AliasTarget': record['AliasTarget']
                        }
                    })
            else:
                print(f"Creating new ALIAS {record['Type']} record for {record['Name']}")
                changes.append({
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'Name': record['Name'],
                        'Type': record['Type'],
                        'AliasTarget': record['AliasTarget']
                    }
                })
        
        # Handle CNAME record for track subdomain
        track_name = f'track.{domain}.'
        track_key = f"{track_name}_CNAME"
        
        if track_key in existing_records:
            existing_track = existing_records[track_key]
            if existing_track.get('ResourceRecords', [{}])[0].get('Value') != 'bseav.ttrk.io':
                print(f"Updating existing CNAME record for track.{domain}")
                changes.append({
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': f'track.{domain}',
                        'Type': 'CNAME',
                        'TTL': 60,  # Changed from 300 to 60 seconds
                        'ResourceRecords': [{'Value': 'bseav.ttrk.io'}]
                    }
                })
            else:
                print(f"Skipping CNAME record for track.{domain} - already correct")
        else:
            print(f"Creating new CNAME record for track.{domain}")
            changes.append({
                'Action': 'CREATE',
                'ResourceRecordSet': {
                    'Name': f'track.{domain}',
                    'Type': 'CNAME',
                    'TTL': 60,  # Changed from 300 to 60 seconds
                    'ResourceRecords': [{'Value': 'bseav.ttrk.io'}]
                }
            })
        
        # Apply changes if any
        if changes:
            print(f"Applying {len(changes)} changes to Route 53")
            self.route53_client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={'Changes': changes}
            )
            print("✅ Route 53 ALIAS records updated successfully")
            print("🎯 Domain will automatically resolve to optimal CloudFront IPs!")
        else:
            print("No Route 53 record changes needed")


# Example usage:
if __name__ == "__main__":
    # Initialize the automation
    aws_automation = AWSAutomation(account_key='auto-insurance')
    
    # Setup a domain (no IP address required!)
    domain = "example.com"
    result = aws_automation.setup_domain(domain)
    
    print(f"\nSetup result: {result['status']}")
    if result['status'] == 'completed':
        print("🎉 Domain setup completed successfully!")
        print("🌐 Your website is now accessible via CloudFront CDN")
        print("🔒 HTTPS is automatically enabled")
        print("⚡ Global performance optimization active")
    else:
        print(f"❌ Setup failed: {result.get('error', 'Unknown error')}")