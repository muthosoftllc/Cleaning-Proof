# Product spec

Cleaning Proof is an Android-first SaaS for professional cleaners and cleaning companies. It documents what was cleaned, when, by whom and in what condition, and turns that into a professional proof-of-cleaning report for the customer.

## Users

Independent cleaners, Airbnb and short-term-rental cleaners, residential cleaning businesses, commercial and janitorial teams, property managers who use cleaning contractors, and cleaning companies with several employees.

## Core workflow

```
Create organization → Add customers/properties → Create job → Select checklist
→ Start job → Complete tasks → Before/after photos → Record issues/damage
→ Finish job → (optional) customer review/signature → Report → Share link
```

## Principles

1. **Fast job execution > reliable evidence > simple reports > beautiful UI > advanced features.**
2. The app should feel like a professional field tool, not a generic task manager. A normal job should take minimal typing and minimal taps.
3. Photo capture is a core feature, not an attachment bolted on afterwards.
4. Offline-first is a hard requirement. Cleaners work inside buildings with no signal, and evidence must never be silently lost.
5. Trust is the product. Reports should be useful enough that customers *want* to receive them, so we avoid aggressive advertising and show only a subtle "Powered by Cleaning Proof".
6. Customers never need an account to view a report.

## Feature summary

- **Jobs**: property and customer, assignee, schedule, status (Scheduled / In progress / Completed / Cancelled), checklist, task completion, before/after photos, notes, issues, start and end time, optional GPS, optional customer signature, generated report.
- **Checklists**: reusable templates organized into rooms or sections, with required and optional tasks, reordering, duplication, and property-specific templates.
- **Photos**: before, after, task and room photos, issue photos, multiple per item, automatic timestamp, optional GPS, compression, private storage, offline capture with later upload.
- **Issues**: room, description, photos, severity, timestamp, and whether the problem was already there or found while cleaning. Example: "Large stain already present on bedroom carpet before cleaning."
- **Proof report**: company branding, property, date, cleaner, times, checklist, photos, issues, notes, signature, unique report ID (`CP-2026-8F42K9`), a verification URL with a QR code, and the generation time. Delivered as a web page, a PDF, and a secure link.
- **Customer page**: view the report, approve and sign, report a problem. A rating may come later.
- **Verification** (`/r/<id>`): confirms the report exists, the company, the property, the completion time, and the integrity status, without exposing private customer data.
- **Dashboard**: today, upcoming, completed and overdue jobs; employees, customers, properties, templates and reports. Metrics are jobs completed, completion rate, average duration, frequently missed tasks, issues reported and customer approvals.
- **Team**: Owner, Admin, Cleaner and Viewer roles. Cleaners only see the data their assigned work needs.
- **Properties**: customer, address, cleaning instructions, default checklist, assigned cleaners, and cleaning history.
- **Recurring jobs**: daily, weekly (e.g. Mon + Thu), biweekly, monthly, or every N days. Upcoming jobs are created automatically and the cleaner is notified.
- **Notifications**: job assigned, starting soon, overdue, completed, report generated, customer approval, customer issue, recurring job created.
- **Subscription** (Google Play Billing, entitlements decided by the server):
  - **Free**: limited jobs and properties, 1 member. Includes photos and customer links, since every report a customer sees is part of the growth loop.
  - **Pro** (~$14.99/mo): unlimited jobs, more properties, PDF reports, recurring jobs, team members.
  - **Business** (~$39.99/mo): multiple teams, advanced permissions, branding, analytics, priority support, more storage.

## Growth loop

```
Cleaner uses Cleaning Proof → Customer receives report → sees "Powered by Cleaning Proof"
→ customer manages multiple properties → needs the same system → becomes a user
```
