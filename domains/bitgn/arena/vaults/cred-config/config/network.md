# Network Configuration

## Load Balancer
- Type: Application Load Balancer
- Instances: 3
- Health check: /healthz every 30s

## CDN
- Provider: CloudFront
- Distribution: d1234567890.cloudfront.net
- Cache TTL: 3600s

## DNS
- Primary: ns1.company.com
- Secondary: ns2.company.com
