# Plugins Reference

## Development
- **pr-review-toolkit**: 6 specialized review agents (code, tests, errors, types, comments, simplification)
- **code-review**: 4 parallel agents for PR review with confidence scoring
- **code-simplifier**: Autonomous code refinement agent
- **feature-dev**: 7-phase structured feature development with competing architectures

## Git Workflow
- **commit-commands**: `/commit`, `/commit-push-pr`, `/clean_gone` for streamlined git workflow
- **hookify**: Create custom hooks from natural language descriptions

## Project Setup
- **claude-code-setup**: Codebase analysis and automation recommendations (this plugin)
- **claude-md-management**: CLAUDE.md quality auditing and session learning capture

## Security
- **security-guidance**: PreToolUse hook for security warnings on file edits

## Frontend
- **frontend-design**: Production-grade UI generation with bold aesthetics

## LSP
- **pyright-lsp**: Python type checking and code intelligence
- **typescript-lsp**: TypeScript/JS language server
- (Plus: gopls, rust-analyzer, clangd, jdtls, kotlin, swift, csharp, php, lua, ruby)

## Plugin Management
- Install: `claude plugin install <name>`
- List: `claude plugin list`
- Remove: `claude plugin remove <name>`
