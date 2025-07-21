import os
from dotenv import load_dotenv


load_dotenv()

class Config:
        # Proxy Configuration (Oxylabs)
    PROXY_USERNAME = os.getenv('PROXY_USERNAME')
    PROXY_PASSWORD = os.getenv('PROXY_PASSWORD')  # or use PROXY_PASSWORD_ENC if you run into URL issues
    PROXY_HOST = os.getenv('PROXY_HOST', 'ddc.oxylabs.io')
    PROXY_PORT = os.getenv('PROXY_PORT', '8001')

    @classmethod
    def get_proxy(cls):
        proxy_url = f"http://{cls.PROXY_USERNAME}:{cls.PROXY_PASSWORD}@{cls.PROXY_HOST}:{cls.PROXY_PORT}"
        return {
            "http": proxy_url,
            "https": proxy_url
        }
    
    # Default AWS account (Auto-insurance_AWS)
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    
    # Second AWS account (Other vertical AWS)
    AWS_ACCESS_KEY_ID_OTHER = os.getenv('AWS_ACCESS_KEY_ID_OTHER')
    AWS_SECRET_ACCESS_KEY_OTHER = os.getenv('AWS_SECRET_ACCESS_KEY_OTHER')
    AWS_REGION_OTHER = os.getenv('AWS_REGION_OTHER', 'us-east-1')
    
    # Namecheap API configuration
    NAMECHEAP_API_USER = os.getenv('NAMECHEAP_API_USER')
    NAMECHEAP_API_KEY = os.getenv('NAMECHEAP_API_KEY')
    NAMECHEAP_CLIENT_IP = os.getenv('NAMECHEAP_CLIENT_IP')
    NAMECHEAP_API_URL = os.getenv('NAMECHEAP_API_URL', 'https://api.namecheap.com/xml.response')
    
    # Admin Credentials and Flask secret key
    FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY')
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
    
    
    # AWS Account configurations
    AWS_ACCOUNTS = {
        'auto-insurance': {
            'name': 'Auto-insurance_AWS',
            'access_key_id': AWS_ACCESS_KEY_ID,
            'secret_access_key': AWS_SECRET_ACCESS_KEY,
            'region': AWS_REGION
        },
        'other-vertical': {
            'name': 'Other vertical AWS',
            'access_key_id': AWS_ACCESS_KEY_ID_OTHER,
            'secret_access_key': AWS_SECRET_ACCESS_KEY_OTHER,
            'region': AWS_REGION_OTHER
        }
    }
    
    # S3 bucket policy template
    BUCKET_POLICY_TEMPLATE = '''{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicRead",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": [
                "arn:aws:s3:::{bucket_name}/*",
                "arn:aws:s3:::{bucket_name}/*/*"
            ]
        }
    ]
}'''