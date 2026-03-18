# Database Migration Plan

**Target:** Migrate from PostgreSQL 14 to PostgreSQL 16
**Estimated downtime:** 2 hours

## Prerequisites (ALL must be met before starting)

1. **API v2 deployed** — see `projects/api-v2-status.md`
   - API v2 must be running in production (backward-compatible with new DB schema)

2. **Backup system verified** — see `ops/backup-status.md`
   - Full backup + point-in-time recovery must be tested and confirmed working

3. **DBA approval** — see `approvals/dba-signoff.md`
   - Written approval from DBA team required (valid for 30 days)

4. **Maintenance window scheduled** — see `ops/maintenance-windows.md`
   - Must have an approved maintenance window booked
