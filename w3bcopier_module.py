from flask import Blueprint, request, send_file, jsonify, render_template, current_app
from flask_login import login_required
import os
import requests
from bs4 import BeautifulSoup
import wget
import shutil
from urllib.parse import urljoin, urlparse, urlunparse
import time
import uuid
import re
import json
import mimetypes
import hashlib
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import chardet

# Create a Blueprint for the w3bcopier routes
w3bcopier_bp = Blueprint('w3bcopier', __name__)

# Use the main app's logger

def render_with_selenium(url, wait_time=10):
    """Use Selenium to render JavaScript-heavy (Next.js) pages."""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-gpu')
    
    # Add experimental options for better Next.js handling
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    try:
        # Initialize driver
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        
        # Set page load timeout
        driver.set_page_load_timeout(30)
        
        # Navigate to URL
        driver.get(url)
        
        # Wait for page to be fully loaded
        WebDriverWait(driver, wait_time).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        
        # Wait for Next.js components to load
        try:
            # Wait for main content to be visible
            WebDriverWait(driver, wait_time).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'main, div[data-testid], div[data-nextjs]'))
            )
            
            # Wait for any dynamic content to load
            WebDriverWait(driver, wait_time).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, 'script')) > 0
            )
            
            # Wait for any pending network requests
            time.sleep(wait_time)  # Let JavaScript finish rendering
            
            # Get final page source
            html = driver.page_source
            
            # Check if page is still loading
            loading_elements = driver.find_elements(By.CSS_SELECTOR, '[role="progressbar"], .loading, .spinner')
            if loading_elements:
                time.sleep(wait_time)  # Wait extra time if loading indicators are present
                html = driver.page_source
            
            return html
            
        except Exception as e:
            current_app.logger.error(f"Error waiting for Next.js content: {str(e)}")
            # Try to get page source even if some elements didn't load
            return driver.page_source
            
    except Exception as e:
        current_app.logger.error(f"Error rendering page with Selenium: {str(e)}")
        return None
    finally:
        try:
            driver.quit()
        except:
            pass

def download_css_background_images(soup, base_url, save_dir):
    """
    Extract and download background images from both internal and external CSS
    """
    current_app.logger.info("Starting background image extraction from CSS")
    
    # Create images directory if it doesn't exist
    img_dir = os.path.join(save_dir, 'images')
    os.makedirs(img_dir, exist_ok=True)
    
    # Function to extract background image URLs from CSS content
    def extract_bg_images(css_content):
        # Common CSS background image patterns
        patterns = [
            r'(background-image\s*:\s*url\()([\'"]?)(.*?)([\'"]?)(\))',
            r'background\s*:\s*.*?url\([\'"]?(.*?)[\'"]?\)',
            r'background-.*?\s*:\s*.*?url\([\'"]?(.*?)[\'"]?\)'
        ]
        
        bg_urls = []
        for pattern in patterns:
            matches = re.findall(pattern, css_content)
            for match in matches:
                # Clean up URL (remove quotes, etc.)
                url = match.strip()
                if url:
                    bg_urls.append(url)
        
        return bg_urls
    
    # Function to download background image and return local path
    def download_bg_image(img_url):
        try:
            if not img_url:
                return None
                
            # Handle data URLs
            if img_url.startswith('data:'):
                return img_url
                
            # Handle relative URLs
            if not img_url.startswith(('http://', 'https://')):
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url
                else:
                    img_url = urljoin(base_url, img_url)
            
            # Generate filename from URL
            filename = safe_filename(img_url)
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')):
                filename += '.png'  # Default extension
            
            local_path = os.path.join('../images/', filename)  # Using ./images/ for CSS path
            full_path = os.path.join(save_dir, 'images/', filename)  # Actual file path doesn't include ./
            
            # Skip if already downloaded
            if os.path.exists(full_path):
                return local_path
                
            # Download the image
            response = requests.get(img_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }, stream=True, timeout=10)
            
            if response.status_code == 200:
                with open(full_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                current_app.logger.info(f"Downloaded background image: {img_url} -> {local_path}")
                return local_path
            else:
                current_app.logger.warning(f"Failed to download background image: {img_url} (Status: {response.status_code})")
                return None
                
        except Exception as e:
            current_app.logger.error(f"Error downloading background image {img_url}: {str(e)}")
            return None
    
    # Function to replace background image URLs in CSS content
    def replace_bg_images(css_content, base_url):
        def replace_url(match):
            url_group = match.group(1)
            if not url_group:
                return match.group(0)
                
            # Download the image and get local path
            local_path = download_bg_image(url_group)
            if local_path:
                # Return the CSS with replaced URL
                return match.group(0).replace(url_group, local_path)
            else:
                return match.group(0)
        
        # Process each background image pattern
        for pattern in [
            r'(background-image\s*:\s*url\()([\'"]?)(.*?)([\'"]?)(\))',
            r'(background\s*:[^;]*?url\()([\'"]?)(.*?)([\'"]?)(\))',
            r'(background-.*?\s*:[^;]*?url\()([\'"]?)(.*?)([\'"]?)(\))'
        ]:
            css_content = re.sub(
                pattern,
                lambda m: m.group(1) + m.group(2) + 
                           (download_bg_image(m.group(3)) or m.group(3)) + 
                           m.group(4) + m.group(5),
                css_content
            )
        
        return css_content
    
    # 1. Process internal CSS (style tags)
    for style in soup.find_all('style'):
        if style.string:
            css_content = style.string
            updated_css = replace_bg_images(css_content, base_url)
            style.string = updated_css
    
    # 2. Process external CSS files
    css_dir = os.path.join(save_dir, 'css')
    if os.path.exists(css_dir):
        for css_file in os.listdir(css_dir):
            css_path = os.path.join(css_dir, css_file)
            try:
                with open(css_path, 'r', encoding='utf-8', errors='ignore') as f:
                    css_content = f.read()
                
                # Process and update CSS content with local image paths
                updated_css = replace_bg_images(css_content, base_url)
                
                with open(css_path, 'w', encoding='utf-8') as f:
                    f.write(updated_css)
                    
                current_app.logger.info(f"Processed background images in CSS file: {css_file}")
            except Exception as e:
                current_app.logger.error(f"Error processing CSS file {css_file}: {str(e)}")
    
    # 3. Process inline styles in HTML
    for element in soup.find_all(style=True):
        inline_style = element['style']
        updated_style = replace_bg_images(inline_style, base_url)
        element['style'] = updated_style
    
    return soup

# Function to remove unnecessary scripts from <script> tags
def is_tracking_script(script_content):
    """
    Checks if the script contains specific tracking or unnecessary backend code.
    """
    # Check for Ringba scripts
    if 'ringba' in script_content.lower():
        return True
    
    # Check for Google Tag Manager patterns
    if any(keyword in script_content.lower() for keyword in ['googletagmanager.com', 'gtag', 'gtm']):
        return True
    
    # Check for specific Google Analytics pattern
    if 'window.dataLayer' in script_content and 'gtag' in script_content:
        return True
    
    # Check for other tracking patterns
    tracking_patterns = [
        'analytics',
        'tracking',
        'advertising',
        'marketing',
        'pixel',
        'beacon',
        'collector',
        'stats',
        'monitor'
    ]
    
    # Check if script contains any of the tracking patterns
    if any(pattern in script_content.lower() for pattern in tracking_patterns):
        return True
    
    return False

# def remove_unnecessary_scripts(soup):
#     """Remove unnecessary <script> tags"""
#     for script in soup.find_all('script'):
#         if script.string and is_tracking_script(script.string):
#             script.decompose()
              # Remove the script if it matches the tracking patterns

# Function to replace external domains with original domain and then replace with replacement domains
# Replace this function in your app.py file

def remove_external_domains(soup, original_domain, replacement_domains):
    """Replace exact matches of the original domain, preserving case sensitivity."""
    preserve_cdns = [
        'fontawesome.com', 'cdn.jsdelivr.net', 'cdn.tailwindcss.com', 'googleapis.com', 
        'bootstrap.css', 'bootstrapcdn.com', 'cdn.cloud', 'jquery.com', 
        'cdnjs.cloudflare.com', 'unpkg.com'
    ]

    # Step 1: Replace external domains (not equal to original_domain) with the original domain
    for tag in soup.find_all(['a', 'img', 'script', 'link']):
        attr = 'href' if tag.name in ['a', 'link'] else 'src'
        src = tag.get(attr)
        if not src:
            continue

        parsed_url = urlparse(src)
        domain = parsed_url.netloc
        domain_lower = domain.lower()  # Use lowercase only for comparison

        if any(cdn in domain_lower for cdn in preserve_cdns):
            continue

        # Only replace if domain != original and NOT a subdomain of original
        if domain_lower and domain_lower != original_domain.lower() and not domain_lower.endswith(f".{original_domain.lower()}"):
            # Keep the original case when replacing
            new_url = src.replace(domain, original_domain)
            tag[attr] = new_url

    # Step 2: Replace exact original_domain with replacement_domain
    if replacement_domains:
        for replacement_domain in replacement_domains:
            for tag in soup.find_all(['a', 'img', 'script', 'link']):
                attr = 'href' if tag.name in ['a', 'link'] else 'src'
                src = tag.get(attr)
                if not src:
                    continue

                parsed_url = urlparse(src)
                domain = parsed_url.netloc
                domain_lower = domain.lower()  # Use lowercase only for comparison

                # Only replace if it's an exact match (no subdomains)
                if domain_lower == original_domain.lower():
                    # Case-sensitive replacement
                    if domain.isupper():
                        replacement = replacement_domain.upper()
                    elif domain.islower():
                        replacement = replacement_domain.lower()
                    elif domain[0].isupper():
                        replacement = replacement_domain.capitalize()
                    else:
                        replacement = replacement_domain
                        
                    new_url = src.replace(domain, replacement)
                    tag[attr] = new_url
    
    return soup

def get_file_extension(url, content_type=None):
    """Get file extension from URL or content type"""
    # Try to get extension from URL first
    ext = os.path.splitext(urlparse(url).path)[1]
    if ext:
        return ext.lower()

    # If no extension in URL, try to get from content type
    if content_type:
        ext = mimetypes.guess_extension(content_type)
        if ext:
            return ext.lower()

    # Default extensions based on content type patterns
    if content_type:
        if 'image' in content_type:
            return '.jpg'
        if 'video' in content_type:
            return '.mp4'
        if 'javascript' in content_type:
            return '.js'
        if 'css' in content_type:
            return '.css'
        if 'font' in content_type:
            return '.woff2'
    
    return '.bin'  # Default extension if nothing else works

def safe_filename(url):
    """
    Convert URL to a safe filename while preserving the original name
    """
    # Get the last part of the URL (filename)
    filename = os.path.basename(urlparse(url).path)
    if not filename:
        filename = 'index'
    
    # Remove query parameters if present
    filename = filename.split('?')[0]
    
    # Keep only the filename without path
    filename = os.path.basename(filename)
    
    # Replace unsafe characters while preserving the original name
    # Only replace characters that are not allowed in Windows filenames
    unsafe_chars = r'[<>:"/\\|?*]'
    filename = re.sub(unsafe_chars, '_', filename)
    
    # Remove leading/trailing spaces and dots
    filename = filename.strip().strip('.')
    
    # If filename is empty after cleaning, use a default name
    if not filename:
        filename = 'unnamed'
    
    return filename

def safe_download(url, save_path):
    try:
        # Ensure the URL is valid
        parsed_url = urlparse(url)
        if not parsed_url.scheme:
            url = 'https://' + url
        if not parsed_url.scheme and not parsed_url.netloc:
            return None

        # Download with timeout and proper headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, stream=True, timeout=(10, 30), headers=headers, allow_redirects=True)
        response.raise_for_status()

        # Get content type and extension
        content_type = response.headers.get('Content-Type', '').split(';')[0]
        ext = get_file_extension(url, content_type)

        # Create unique filename using hash of URL
        url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
        filename = f"{url_hash}{ext}"
        full_path = os.path.join(save_path, filename)

        # Save file with proper encoding to handle unicode characters
        with open(full_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return filename
    except Exception as e:
        print(f'Error downloading {url}: {str(e)}')
        return None

# Function to replace domain in URL
def replace_domain_in_url(url, original_domains, new_domains, base_url):
    try:
        full_url = urljoin(base_url, url)
        parsed = urlparse(full_url)
        
        if not parsed.netloc:
            return url

        current_domain = parsed.netloc.replace('www.', '')
        
        for orig_domain, new_domain in zip(original_domains, new_domains):
            orig_domain = orig_domain.strip().lower().replace('www.', '')
            new_domain = new_domain.strip().lower().replace('www.', '')
            
            if current_domain == orig_domain:
                new_url = full_url.replace(parsed.netloc, new_domain)
                return new_url
    except:
        pass
    return url


# Replace this function in your app.py file

def replace_text_content(text, original_domains, replacement_domains):
    """
    Replace not just domains but any text content from original to replacement.
    This preserves case sensitivity during replacement to maintain exact formatting.
    """
    if not text:
        return text
    
    # Process each domain/text pair
    for orig_domain, repl_domain in zip(original_domains, replacement_domains):
        orig_domain = orig_domain.strip()  # Don't convert to lowercase
        repl_domain = repl_domain.strip()  # Don't convert to lowercase
        
        # Create case-insensitive pattern but use case-sensitive replacement
        pattern = re.compile(re.escape(orig_domain), re.IGNORECASE)
        
        # Custom replacement function to preserve case
        def match_case(match):
            matched_text = match.group(0)
            
            # If original is all uppercase, make replacement all uppercase
            if matched_text.isupper():
                return repl_domain.upper()
            
            # If original is all lowercase, make replacement all lowercase
            elif matched_text.islower():
                return repl_domain.lower()
            
            # If original starts with capital, capitalize replacement
            elif matched_text[0].isupper():
                return repl_domain.capitalize()
            
            # Otherwise use replacement as is
            else:
                return repl_domain
                
        # Apply case-preserving replacement
        text = pattern.sub(match_case, text)
        
        # Handle www prefix case-sensitively too
        www_pattern = re.compile(r'www\.' + re.escape(orig_domain), re.IGNORECASE)
        
        def www_match_case(match):
            matched_text = match.group(0)
            www_part = matched_text[:4]  # Extract 'www.' part
            domain_part = matched_text[4:]  # Extract domain part
            
            # Apply same case logic to domain part
            if domain_part.isupper():
                return www_part + repl_domain.upper()
            elif domain_part.islower():
                return www_part + repl_domain.lower()
            elif domain_part[0].isupper():
                return www_part + repl_domain.capitalize()
            else:
                return www_part + repl_domain
                
        text = www_pattern.sub(www_match_case, text)
        
        # Replace encoded versions (for JavaScript/JSON content)
        text = text.replace(f'\\"{orig_domain}\\"', f'\\"{repl_domain}\\"')
        text = text.replace(f"\\'{orig_domain}\\'", f"\\'{repl_domain}\\'")
        
        # Replace URL-encoded versions
        text = text.replace(f'%22{orig_domain}%22', f'%22{repl_domain}%22')
    
    return text
def download_and_save_asset(url, base_url, save_path, asset_type):
    """Download and save an asset, checking for HTTPS calls in JavaScript files"""
    try:
        # Handle relative URLs and make them absolute
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            url = urljoin(base_url, url)
        elif not url.startswith(('http://', 'https://')):
            url = urljoin(base_url, url)

        # Skip if already downloaded
        if os.path.exists(save_path):
            return True

        # Download the asset
        response = requests.get(url, stream=True, timeout=10)
        response.raise_for_status()

        # For JavaScript files, check for HTTPS calls (we want to avoid any HTTP calls in JS)
        if asset_type == 'js':
            content = response.text
            if 'https' in content.lower():
                print(f"Removing script with HTTPS calls: {url}")
                return False

        # Save the asset to the disk
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True

    except Exception as e:
        print(f"Error downloading {url}: {str(e)}")
        return False

def contains_https_calls(content):
    """Check if content contains HTTPS calls"""
    if not content:
        return False
    
    # Patterns for HTTPS calls
    patterns = [
        r'https?://[^\s<>"]+',  # URLs
        r'fetch\([\'"](https?://[^\'"]+)[\'"]',  # Fetch calls
        r'XMLHttpRequest\([\'"](https?://[^\'"]+)[\'"]',  # XHR calls
        r'axios\.(get|post|put|delete)\([\'"](https?://[^\'"]+)[\'"]',  # Axios calls
        r'\.ajax\([\'"](https?://[^\'"]+)[\'"]',  # jQuery AJAX calls
        r'new Image\([\'"](https?://[^\'"]+)[\'"]',  # Image loading
        r'\.src\s*=\s*[\'"](https?://[^\'"]+)[\'"]',  # Source assignments
        r'\.href\s*=\s*[\'"](https?://[^\'"]+)[\'"]',  # Href assignments
        r'\.setAttribute\([\'"]src[\'"],\s*[\'"](https?://[^\'"]+)[\'"]',  # setAttribute calls
        r'\.setAttribute\([\'"]href[\'"],\s*[\'"](https?://[^\'"]+)[\'"]',
        r'\.load\([\'"](https?://[^\'"]+)[\'"]',  # jQuery load
        r'\.get\([\'"](https?://[^\'"]+)[\'"]',  # jQuery get
        r'\.post\([\'"](https?://[^\'"]+)[\'"]',  # jQuery post
        r'\.getScript\([\'"](https?://[^\'"]+)[\'"]',  # jQuery getScript
        r'\.getJSON\([\'"](https?://[^\'"]+)[\'"]',  # jQuery getJSON
        r'\.animate\([\'"](https?://[^\'"]+)[\'"]',  # jQuery animate
        r'\.replace\([\'"](https?://[^\'"]+)[\'"]',  # String replace with URL
        r'\.assign\([\'"](https?://[^\'"]+)[\'"]',  # Window location assign
        r'\.replace\([\'"](https?://[^\'"]+)[\'"]',  # Window location replace
        r'\.open\([\'"](https?://[^\'"]+)[\'"]',  # Window open
        r'\.createElement\([\'"]script[\'"]\)',  # Dynamic script creation
        r'\.appendChild\([^)]+\)',  # appendChild with potential script
        r'\.insertBefore\([^)]+\)',  # insertBefore with potential script
        r'eval\([^)]+\)',  # eval calls
        r'new Function\([^)]+\)',  # Function constructor
        r'\.importScripts\([^)]+\)',  # importScripts
        r'\.import\([^)]+\)',  # dynamic imports
        r'require\([^)]+\)',  # require calls
        r'import\s+[^;]+from\s+[\'"][^\'"]+[\'"]'  # ES6 imports
    ]
    
    return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)

def remove_tracking_keywords_from_script(script_content):
    """Remove specific tracking keywords from script content while preserving format."""
    # List of tracking patterns to detect and remove
    tracking_patterns = [
        # Google Analytics patterns
        r'gtag_report_conversion',
        r'window.dataLayer = window.dataLayer || \[\]',
        r'function gtag\(\){dataLayer.push\(arguments\);}',
        r'gtag\(\'event\', \'conversion\',',
        r'AW-[0-9]+/[A-Za-z0-9]+',  # Google Analytics conversion ID pattern
        r'ga\(\'create\',',
        r'ga\(\'send\',',
        r'google-analytics',
        r'UA-[0-9]+-[0-9]+',  # Universal Analytics ID pattern
        
        # Facebook tracking patterns
        r'fbq\(\'track\',',
        r'fbq\(\'init\',',
        r'facebook-pixel',
        r'pixel\.',
        
        # Google Tag Manager patterns
        r'googletagmanager',
        r'GTM-[A-Z0-9]+',  # GTM ID pattern
        r'gtm\.',
        r'dataLayer',
        
        # General tracking patterns
        r'track\(',
        r'tracking\.',
        r'pixel\.',
        r'conversion\.',
        r'reportConversion',
        r'collect\(',
        r'beacon\.',
        r'monitor\.',
        
        # Marketing and analytics patterns
        r'advertising\.',
        r'analytics\.',
        r'marketing\.',
        r'campaign\.',
        r'attribution\.',
        
        # Specific tracking functions
        r'function track\(',
        r'function pixel\(',
        r'function conversion\(',
        r'function report\(',
        r'function collect\(',
        
        # Common tracking domains
        r'google-analytics\.com',
        r'googletagmanager\.com',
        r'facebook\.com/tr',
        r'facebook\.net/tr',
        r'pixel\.io',
        r'track\.',
        
        # Specific tracking IDs
        r'AW-[0-9]+',  # Google AdWords conversion ID
        r'UA-[0-9]+-[0-9]+',  # Universal Analytics ID
        r'GTM-[A-Z0-9]+',  # Google Tag Manager ID
        r'FB-[0-9]+',  # Facebook Pixel ID
        
        # Ringba patterns
        r'ringba\.',
        r'b-js\.ringba\.com',
        r'CA[0-9a-f]+',  # Ringba campaign ID pattern
        
        # Other tracking patterns
        r'landerlab',
        r'clickfunnels',
        r'cf\.js',
        r'pixel\.',
        r'conversion\.',
        r'report\.',
        r'collect\.',
        r'monitor\.',
        r'track\.',
        r'advertising\.',
        r'analytics\.',
        r'marketing\.',
        r'pixel\.',
        r'beacon\.',
        r'collector\.',
        r'stats\.',
        r'monitor\.',
        
        # Specific tracking function patterns
        r'function gtag_report_conversion',
        r'function trackConversion',
        r'function trackEvent',
        r'function trackPage',
        r'function trackClick',
        r'function trackForm',
        r'function trackLead',
        r'function trackSale',
        r'function trackSignup',
    ]

    # Split the script into lines to preserve formatting
    script_lines = script_content.splitlines()
    cleaned_script_lines = []

    # Track if we're in a tracking block
    in_tracking_block = False
    
    for line in script_lines:
        # Check if we're entering a tracking block
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in tracking_patterns):
            in_tracking_block = True
            continue
        
        # Skip lines while in tracking block
        if in_tracking_block:
            # Reset if we find the end of the block
            if any(x in line.lower() for x in ['return false', '};', ')', '}', ';']) and not any(re.search(pattern, line, re.IGNORECASE) for pattern in tracking_patterns):
                in_tracking_block = False
            continue
        
        # Add the line if it's not in a tracking block
        cleaned_script_lines.append(line)

    # Join the cleaned lines back into a single string to preserve the original formatting
    cleaned_script = "\n".join(cleaned_script_lines)
    
    # If the script was completely tracking-related, return an empty string
    if not cleaned_script.strip():
        return ""
    
    return cleaned_script

# Modify this part of your remove_tracking_scripts function in app.py

def remove_tracking_scripts(soup, remove_tracking=False, remove_custom_tracking=False, remove_redirects=False, save_dir=None, base_url=None):
    """Remove tracking-related code from the HTML script content without removing the whole script tag."""

    # Skip if no tracking removal is requested - this is the main check to respect user choices
    if not (remove_tracking or remove_custom_tracking or remove_redirects):
        current_app.logger.info("No tracking removal requested - skipping all tracking script operations")
        return soup

    current_app.logger.info(f"Tracking removal options - Remove tracking: {remove_tracking}, Remove custom tracking: {remove_custom_tracking}, Remove redirects: {remove_redirects}")

    # List of trusted CDNs
    trusted_cdns = [
        'cdnjs.cloudflare.com',
        'unpkg.com',
        'jsdelivr.net',
        'bootstrapcdn.com',
        'jquery.com',
        'cdn.jsdelivr.net',
        'bootstrap.com',
        'fontawesome.com',
        'googleapis.com',
        'microsoft.com',
        'cloudflare.com',
        'amazonaws.com',
        'cloudfront.net'
    ]

    def is_trusted_cdn(url):
        """Check if URL is from a trusted CDN."""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        return any(cdn in domain for cdn in trusted_cdns)

    # Remove scripts with tracking keywords in src attributes
    tracking_keywords = [
        'ringba',
        'googletagmanager.com',
        'gtag',
        'gtm',
        'fbq',
        'track',
        'pixel',
        'analytics'
    ]

    for script in soup.find_all('script'):
        # Check src attribute for tracking keywords
        src = script.get('src')
        if src:
            # Skip trusted CDNs
            if is_trusted_cdn(src):
                continue
            
            # Only remove if tracking removal is enabled
            if remove_tracking and any(keyword in src.lower() for keyword in tracking_keywords):
                current_app.logger.info(f"Removing tracking script with src: {src}")
                script.decompose()
                continue

        # Check if the script has landerlab-* attributes or contains landerlab in content
        if any(attr.startswith('landerlab') for attr in script.attrs):
            # Only remove if custom tracking removal is enabled (note the changed logic)
            if remove_custom_tracking:
                current_app.logger.info(f"Removing landerlab script: {script}")
                script.decompose()
            continue

        # Check for custom track.js scripts
        if src and 'track.js' in src and remove_custom_tracking:
            current_app.logger.info(f"Removing custom track.js script: {src}")
            script.decompose()
            continue

        if script.string:  # Only process inline scripts, not src-based ones
            original_script_content = script.string

            # Only modify script content if tracking removal is enabled
            if remove_tracking:
                # Remove tracking keywords from the script content
                cleaned_script_content = remove_tracking_keywords_from_script(original_script_content)

                # Only update the script if any changes were made
                if cleaned_script_content != original_script_content:
                    script.string = cleaned_script_content

    # Remove meta tags related to tracking (if tracking removal is enabled)
    if remove_tracking:
        for meta in soup.find_all('meta'):
            # Check meta content for tracking keywords
            content = meta.get('content', '').lower()
            if any(keyword in content for keyword in tracking_keywords):
                current_app.logger.info(f"Removing tracking meta: {meta}")
                meta.decompose()

    # Remove noscript tags that might contain tracking pixels (if tracking removal is enabled)
    if remove_tracking:
        for noscript in soup.find_all('noscript'):
            # Check if noscript contains tracking elements
            noscript_content = str(noscript).lower()
            
            # List of tracking keywords to check in noscript content
            tracking_keywords = [
                'gtag',
                'googletagmanager',
                'gtm',
                'ringba',
                'pixel',
                'meta',
                'fb',
                'google tag manager'
            ]
            
            # Check if any tracking keyword is present
            if any(keyword in noscript_content for keyword in tracking_keywords):
                current_app.logger.info(f"Removing tracking noscript: {noscript}")
                noscript.decompose()
                continue

            # Check if noscript contains an iframe
            iframe = noscript.find('iframe')
            if iframe:
                # Check iframe src for tracking keywords
                src = iframe.get('src', '').lower()
                if any(keyword in src for keyword in tracking_keywords):
                    current_app.logger.info(f"Removing tracking iframe: {iframe}")
                    noscript.decompose()
                    continue

    # Remove inline tracking scripts from onclick and other event handlers (if tracking removal is enabled)
    if remove_tracking:
        for element in soup.find_all(True):
            for attr in list(element.attrs):
                if attr.startswith('on'):
                    value = element[attr].lower()
                    if any(keyword in value for keyword in tracking_keywords):
                        del element[attr]

    # Remove links that redirect to external sites (if redirects removal is enabled)
    # if remove_redirects:
    #     for link in soup.find_all('a', href=True):
    #         href = link['href']
    #         if urlparse(href).netloc and urlparse(href).netloc != urlparse(base_url).netloc:
    #             current_app.logger.info(f"Removing external redirect link: {href}")
    #             link.decompose()

    # Remove script tags that redirect to external sites (if redirects removal is enabled)
    if remove_redirects:
        for script in soup.find_all('script'):
            src = script.get('src', '')
            if src and urlparse(src).netloc and urlparse(src).netloc != urlparse(base_url).netloc:
                current_app.logger.info(f"Removing external script: {src}")
                script.decompose()
                
    return soup
def detect_encoding(content):
    """Detects the correct encoding of a webpage."""
    # First try to detect encoding from the content
    detected = chardet.detect(content)
    encoding = detected.get("encoding", "utf-8")
    
    # If confidence is low, try to find encoding in meta tags
    if detected.get("confidence", 0) < 0.8:
        soup = BeautifulSoup(content, 'html.parser')
        meta_charset = soup.find('meta', charset=True)
        if meta_charset:
            return meta_charset['charset']
        
        # Look for content-type meta tag
        meta_content_type = soup.find('meta', attrs={'http-equiv': 'Content-Type'})
        if meta_content_type and 'charset=' in meta_content_type.get('content', ''):
            return meta_content_type['content'].split('charset=')[-1]
    
    return encoding

def download_and_replace_image(img_url, save_dir, base_url):
    """Download image and return local path"""
    try:
        if not img_url.startswith(('http://', 'https://')):
            img_url = urljoin(base_url, img_url)
        
        # Create images directory if it doesn't exist
        img_dir = os.path.join(save_dir, 'images')
        os.makedirs(img_dir, exist_ok=True)
        
        # Generate safe filename
        filename = safe_filename(img_url)
        if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp')):
            filename += '.png'  # Default to PNG if no extension
        
        local_path = os.path.join('images', filename)
        full_path = os.path.join(save_dir, local_path)
        
        # Download the image
        response = requests.get(img_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }, stream=True)
        
        if response.ok:
            with open(full_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return local_path
        return None
    except Exception as e:
        print(f"Error downloading image {img_url}: {str(e)}")
        return None



def download_and_replace_favicon(favicon_url, save_dir, base_url):
    """Download favicon and return local path"""
    try:
        if not favicon_url.startswith(('http://', 'https://')):
            favicon_url = urljoin(base_url, favicon_url)

        # Create icons directory if it doesn't exist
        icon_dir = os.path.join(save_dir, 'icons')
        os.makedirs(icon_dir, exist_ok=True)

        # Generate a safe filename for the favicon
        filename = safe_filename(favicon_url)
        if not filename.lower().endswith(('.ico', '.png', '.jpg', '.jpeg')):
            filename += '.ico'  # Default to .ico if no extension

        local_path = os.path.join('icons', filename)
        full_path = os.path.join(save_dir, local_path)

        # Download the favicon
        response = requests.get(favicon_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }, stream=True)

        if response.ok:
            with open(full_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return local_path
        return None
    except Exception as e:
        print(f"Error downloading favicon {favicon_url}: {str(e)}")
        return None
    
def download_assets(soup, base_url, save_dir):
    """Download all assets and update their references in the HTML"""
    # List of trusted CDNs to keep as HTTPS
    trusted_cdns = [
        'cdnjs.cloudflare.com',
        'unpkg.com',
        'jsdelivr.net',
        'fontawesome.com',
        'cdn.jsdelivr.net',
        'bootstrapcdn.com',
        'bootstrap.com',
        'jquery.com',
        'googleapis.com',
    ]

    # Function to check if the URL is from a trusted CDN
    def is_trusted_cdn(url):
        if not url:
            return False
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        return any(cdn in domain for cdn in trusted_cdns)

    # Function to check if the link is from specific CDNs we want to preserve
    def should_preserve_cdn(url):
        if not url:
            return False
        preserve_patterns = ['fontawesome.com', 'bootstrap.com', 'bootstrapcdn.com', 'jquery.com' ,'cdn.tailwindcss.com' ]
        return any(pattern in url.lower() for pattern in preserve_patterns)

    # Create asset directories
    for asset_type in ['css', 'js', 'images', 'videos', 'icons']:
        os.makedirs(os.path.join(save_dir, asset_type), exist_ok=True)

    # Download CSS files
    for link in soup.find_all('link', rel='stylesheet'):
        href = link.get('href')
        if href:
            # If the URL is relative (starting with '/'), join it with base URL
            if href.startswith('/'):
                href = urljoin(base_url, href)

            # If it's from a CDN we want to preserve, keep the original link
            if should_preserve_cdn(href) or is_trusted_cdn(href):
                # Ensure it's an absolute URL and preserve
                if href.startswith('//'):
                    link['href'] = 'https:' + href  # Ensure it's HTTPS
                elif not href.startswith(('http://', 'https://')):
                    link['href'] = urljoin(base_url, href)
                current_app.logger.info(f"Preserving CDN CSS: {href}")
            else:
                # Otherwise, download locally and update the href
                filename = safe_filename(href)
                save_path = os.path.join(save_dir, 'css', filename)
                if download_and_save_asset(href, base_url, save_path, 'css'):
                    link['href'] = f'css/{filename}'  # Update to local relative path
                    current_app.logger.info(f"Downloaded CSS locally: {href} -> css/{filename}")

    # Download JavaScript files
    for script in soup.find_all('script', src=True):
        src = script.get('src')
        if src:
            # Ensure full URL
            if src.startswith('//'):
                src = 'https:' + src
            elif not src.startswith(('http://', 'https://')):
                src = urljoin(base_url, src)

            # Preserve trusted CDNs
            if should_preserve_cdn(src) or is_trusted_cdn(src):
                script['src'] = src  # Leave as-is (absolute CDN path)
                current_app.logger.info(f"Preserving CDN JS: {src}")
                continue
            
            # Otherwise, download and replace
            filename = safe_filename(src)
            save_path = os.path.join(save_dir, 'js', filename)
            if download_and_save_asset(src, base_url, save_path, 'js'):
                script['src'] = f'js/{filename}'  # Local path
                current_app.logger.info(f"Downloaded JS locally: {src} -> js/{filename}")
            else:
                script.decompose()
                current_app.logger.info(f"Removed JS with HTTPS calls or failed to download: {src}")

    # Download images
    for img in soup.find_all('img'):
        # Check 'src', 'srcset', and 'data-src' (if they exist) for image URLs
        for attr in ['src', 'srcset', 'data-src']:
            src = img.get(attr)
            if src:
                if src.startswith('/'):
                    src = urljoin(base_url, src)

                if should_preserve_cdn(src) or is_trusted_cdn(src):
                    if src.startswith('//'):
                        img[attr] = 'https:' + src
                    elif not src.startswith(('http://', 'https://')):
                        img[attr] = urljoin(base_url, src)
                    current_app.logger.info(f"Preserving CDN Image: {src}")
                else:
                    filename = safe_filename(src)
                    save_path = os.path.join(save_dir, 'images', filename)
                    if download_and_save_asset(src, base_url, save_path, 'images'):
                        img[attr] = f'images/{filename}'
                        current_app.logger.info(f"Downloaded Image locally: {src} -> images/{filename}")
    
    # Download favicon (from <link rel="icon">)
    for link in soup.find_all('link',  rel=['icon', 'apple-touch-icon']):
        href = link.get('href')
        if href:
            if href.startswith('/'):
                href = urljoin(base_url, href)

            # Download the favicon locally and update the href to the local path
            filename = safe_filename(href)
            save_path = os.path.join(save_dir, 'icons', filename)
            local_favicon_path = download_and_replace_favicon(href, save_dir, base_url)
            if local_favicon_path:
                link['href'] = f'icons/{filename}'  # Update to local relative path
                current_app.logger.info(f"Downloaded favicon locally: {href} -> icons/{filename}")

    for source in soup.find_all('source'):
        src = source.get('src')
        if src:
            # If the URL is relative (starting with '/'), join it with base URL
            if src.startswith('/'):
                src = urljoin(base_url, src)

            # Download the video locally and update the src attribute to the local path
            filename = safe_filename(src)
            save_path = os.path.join(save_dir, 'videos', filename)
            if download_and_save_asset(src, base_url, save_path, 'videos'):
                source['src'] = f'videos/{filename}'  # Update to local relative path
                current_app.logger.info(f"Downloaded Video locally: {src} -> videos/{filename}")
def download_additional_pages(soup, base_url, save_dir, original_domains, replacement_domains):
    keywords = ['privacy.html', 'term.html', 'terms.html', 'about.html', 'contact.html' ,'service.html']
    downloaded_pages = {}

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if any(kw in href.lower() for kw in keywords):
            full_url = urljoin(base_url, href)
            try:
                response = requests.get(full_url, headers={
                    'User-Agent': 'Mozilla/5.0'
                }, timeout=10)
                if response.status_code == 200:
                    encoding = detect_encoding(response.content)
                    sub_soup = BeautifulSoup(response.content.decode(encoding), 'html.parser')

                    # Process the new page just like the main one
                    remove_tracking_scripts(sub_soup, True, True, False, save_dir, full_url)
                    download_assets(sub_soup, full_url, save_dir)
                    sub_soup = download_css_background_images(sub_soup, full_url, save_dir)
                    
                    # Replace domains in content
                    html_content = str(sub_soup)
                    html_content = replace_text_content(html_content, original_domains, replacement_domains)
                    
                    # Determine filename
                    filename = re.sub(r'[^a-zA-Z0-9]+', '_', href.strip('/')) or 'page'
                    filename = filename[:30]  # Limit filename length
                    filename += '.html'
                    filepath = os.path.join(save_dir, filename)

                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(html_content)

                    a_tag['href'] = filename
                    downloaded_pages[href] = filename
                    current_app.logger.info(f"Downloaded and linked: {full_url} -> {filename}")
            except Exception as e:
                current_app.logger.warning(f"Failed to fetch {full_url}: {str(e)}")

    return soup
                           
@w3bcopier_bp.route('/')
def index():
    return render_template('web.html')

@w3bcopier_bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'module': 'w3bcopier'})

@w3bcopier_bp.route('/download', methods=['POST'])
@login_required
def download_website():
    try:
        data = request.json
        current_app.logger.info('Received data: %s', data)  # Changed to info level
        if not data:
            current_app.logger.error('Invalid JSON data')
            return jsonify({'error': 'Invalid JSON data'}), 400

        url = data.get('url')
        current_app.logger.info('URL provided: %s', url)
        if not url:
            current_app.logger.error('URL is required')
            return jsonify({'error': 'URL is required'}), 400

        # Handle optional domain replacement
        original_domains = [d.strip() for d in data.get('originalDomain', '').split(',') if d.strip()]
        replacement_domains = [d.strip() for d in data.get('replacementDomain', '').split(',') if d.strip()]
        current_app.logger.info('Original domains: %s', original_domains)
        current_app.logger.info('Replacement domains: %s', replacement_domains)
        
        # Get optional tracking removal settings
        remove_tracking = data.get('removeTracking', False)
        remove_custom_tracking = data.get('removeCustomTracking', False)
        remove_redirects = data.get('removeRedirects', False)
        custom_head_script = data.get('customHeadScript', '').strip()
        
        # Log the checkbox states
        current_app.logger.info('Tracking removal settings - remove_tracking: %s, remove_custom_tracking: %s, remove_redirects: %s', 
                       remove_tracking, remove_custom_tracking, remove_redirects)

        # Validate domains if they are provided
        if original_domains or replacement_domains:
            if not original_domains:
                current_app.logger.error('Original domains are required when using domain replacement')
                return jsonify({'error': 'Original domains are required when using domain replacement'}), 400
            if not replacement_domains:
                current_app.logger.error('Replacement domains are required when using domain replacement')
                return jsonify({'error': 'Replacement domains are required when using domain replacement'}), 400
            if len(original_domains) != len(replacement_domains):
                current_app.logger.error('Number of original domains must match number of replacement domains')
                return jsonify({'error': 'Number of original domains must match number of replacement domains'}), 400
            
            # DON'T convert domains to lowercase to preserve case
            # original_domains = [d.strip() for d in original_domains]
            # replacement_domains = [d.strip() for d in replacement_domains]
            current_app.logger.info('Original domains (preserving case): %s', original_domains)
            current_app.logger.info('Replacement domains (preserving case): %s', replacement_domains)
            # Clean up domain inputs
            original_domains = [d.strip().lower().replace('www.', '') for d in original_domains]
            replacement_domains = [d.strip().lower().replace('www.', '') for d in replacement_domains]
            current_app.logger.info('Cleaned original domains: %s', original_domains)
            current_app.logger.info('Cleaned replacement domains: %s', replacement_domains)

        # Step 2: Download the webpage content
        response = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        response.raise_for_status()
        
        # Step 3: Create save directory
        save_dir = f'temp_website_{int(time.time())}'
        os.makedirs(save_dir, exist_ok=True)
        
        # Step 4: Detect encoding and create soup object
        encoding = detect_encoding(response.content)
        html_content = response.content.decode(encoding)
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Step 5: Remove unnecessary scripts
        # remove_unnecessary_scripts(soup)

        # Step 5.5: Always normalize track.js script src by removing query params
        for script in soup.find_all('script'):
            src = script.get('src')
            if src and 'track.js' in src:
                parsed = urlparse(src)
                if parsed.path.endswith('track.js') and parsed.query:
                    new_src = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
                    script['src'] = new_src

        # Step 6: Remove tracking scripts if requested
        if remove_tracking or remove_custom_tracking or remove_redirects:
            current_app.logger.info('Tracking removal requested - Processing tracking scripts')
            remove_tracking_scripts(soup, remove_tracking, remove_custom_tracking, remove_redirects, save_dir, url)
        else:
            current_app.logger.info('No tracking removal requested - Skipping tracking script removal')

        # Step 8: Download all assets locally
        download_assets(soup, url, save_dir)

        soup = download_css_background_images(soup, url, save_dir)

        soup = download_additional_pages(soup, url, save_dir, original_domains, replacement_domains)


        # Step 9: Replace external domains with the original domain
        remove_external_domains(soup, urlparse(url).netloc, [])

        # Step 10: Replace original domain with replacement domains
        if replacement_domains:
            remove_external_domains(soup, urlparse(url).netloc, replacement_domains)

        # Step 11: Full content domain replacement
        if original_domains and replacement_domains:
            # Replace in full HTML
            html_raw = str(soup)
            html_raw = replace_text_content(html_raw, original_domains, replacement_domains)
            soup = BeautifulSoup(html_raw, 'html.parser')

            # Replace in JS files
            js_path = os.path.join(save_dir, 'js')
            if os.path.exists(js_path):
                for js_file in os.listdir(js_path):
                    full_path = os.path.join(js_path, js_file)
                    try:
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        content = replace_text_content(content, original_domains, replacement_domains)
                        with open(full_path, 'w', encoding='utf-8', errors='ignore') as f:
                            f.write(content)
                    except Exception as e:
                        current_app.logger.error(f'Error processing JS file {js_file}: {str(e)}')

            # Replace in CSS files
            css_path = os.path.join(save_dir, 'css')
            if os.path.exists(css_path):
                for css_file in os.listdir(css_path):
                    full_path = os.path.join(css_path, css_file)
                    try:
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        content = replace_text_content(content, original_domains, replacement_domains)
                        with open(full_path, 'w', encoding='utf-8', errors='ignore') as f:
                            f.write(content)
                    except Exception as e:
                        current_app.logger.error(f'Error processing CSS file {css_file}: {str(e)}')
                        
        # Step 12: Inject custom head script if provided (moved here to ensure all removals/replacements are done first)
        if custom_head_script:
            head = soup.find('head')
            if head:
                custom_head_script_strip = custom_head_script.strip()
                if custom_head_script_strip.startswith('<script') or custom_head_script_strip.startswith('<'):
                    temp_soup = BeautifulSoup(custom_head_script_strip, 'html.parser')
                    for tag in temp_soup.contents:
                        # If it's a <script> tag, reorder attributes
                        if tag.name == 'script':
                            attrs = tag.attrs
                            # Rebuild attrs with type first, then src, then the rest
                            new_attrs = {}
                            if 'src' in attrs:
                                new_attrs['src'] = attrs['src']
                            if 'type' in attrs:
                                new_attrs['type'] = attrs['type']
                            
                            for k, v in attrs.items():
                                if k not in new_attrs:
                                    new_attrs[k] = v
                            tag.attrs = new_attrs
                        head.append(tag)
                    current_app.logger.info('Injected custom head HTML: %s', custom_head_script)
                else:
                    new_script = soup.new_tag('script')
                    # Set type first, then src if present in the code (not typical for inline, but for consistency)
                    new_script['type'] = 'text/javascript'
                    new_script.string = custom_head_script_strip
                    head.append(new_script)
                    current_app.logger.info('Injected custom head JS as <script>: %s', custom_head_script)
        # Step 13: Ensure <script> tags in <head> have type first, then src, then rest
        from collections import OrderedDict
        head = soup.find('head')
        if head:
            for script in head.find_all('script'):
                attrs = script.attrs
                new_attrs = OrderedDict()
                if 'src' in attrs:
                    new_attrs['src'] = attrs['src']
                if 'type' in attrs:
                    new_attrs['type'] = attrs['type']
                
                for k, v in attrs.items():
                    if k not in new_attrs:
                        new_attrs[k] = v
                script.attrs = new_attrs
        # Save final HTML
        with open(os.path.join(save_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(str(soup.prettify()))
        

        # Step 13: Create zip file
        zip_name = f'website_{int(time.time())}.zip'
        shutil.make_archive(os.path.splitext(zip_name)[0], 'zip', save_dir)

        # Step 14: Clean up temp directory
        try:
            shutil.rmtree(save_dir)
        except Exception as e:
            current_app.logger.error('Error cleaning up temporary directory: %s', str(e))
        
        # Step 15: Send the zip
        if os.path.exists(zip_name):
            response = send_file(zip_name, as_attachment=True, mimetype='application/zip')
            try:
                os.remove(zip_name)
                current_app.logger.info('Zip file removed after sending')
            except Exception as e:
                current_app.logger.error('Error removing zip file: %s', str(e))
            return response
        else:
            current_app.logger.error('Error: Zip file not created')
            return jsonify({'error': 'Failed to create zip file'}), 500

    except Exception as e:
        app.logger.error('Exception occurred: %s', str(e))

# The app will be run from app.py
