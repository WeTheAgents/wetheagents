# MCP Servers Reference

## Documentation
- **context7**: Live docs for any library. Recommend when: project uses external libraries.

## Browser Automation
- **Playwright MCP**: Browser testing and interaction. Recommend when: frontend project or E2E tests.
- **Puppeteer MCP**: Lightweight browser control. Recommend when: scraping or simple browser tasks.

## Databases
- **PostgreSQL MCP**: Direct DB interaction. Recommend when: `psycopg2` or `sqlalchemy` in deps.
- **Supabase MCP**: Supabase project management. Recommend when: Supabase config detected.

## Version Control
- **GitHub MCP**: GitHub API integration. Recommend when: `.github/` directory, heavy issue/PR workflow.
- **Linear MCP**: Linear issue tracking. Recommend when: Linear references in code or docs.

## Cloud Infrastructure
- **AWS MCP**: AWS service interaction. Recommend when: `boto3` in deps or AWS config.
- **Cloudflare MCP**: Workers and DNS. Recommend when: `wrangler.toml` detected.

## Monitoring
- **Sentry MCP**: Error tracking. Recommend when: `sentry-sdk` in deps.

## Communication
- **Slack MCP**: Slack messaging. Recommend when: Slack webhooks or bot tokens detected.
- **Notion MCP**: Notion pages and databases. Recommend when: Notion references in docs.

## Code Intelligence
- **Serena**: Symbol-level code navigation via LSP. Recommend when: large codebase (100+ files), multiple languages.
