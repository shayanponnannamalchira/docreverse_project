# Incident Response Runbook

Document ID: IT-310
Owner: IT Service Desk Lead
Last Reviewed: 2025-06-01

## Overview
This runbook describes how the IT Service Desk handles production incidents. The on-call Engineer uses PagerDuty and Jira to coordinate the response. Severity is defined by the Service Level Agreement (SLA).

## Severity 1 Response
A Severity 1 incident is triggered when a customer-facing system is down.

1. PagerDuty pages the on-call Engineer immediately.
2. The on-call Engineer acknowledges the page within 15 minutes.
3. The Incident Commander opens a Jira ticket and starts a bridge call.
4. The Incident Commander notifies the Security Team and the Communications Team.
5. If the outage lasts longer than 60 minutes, the Incident Commander escalates to the VP of Engineering.
6. After resolution, the on-call Engineer writes a Postmortem Report in Confluence within 5 business days.

## Severity 2 Response
1. The IT Service Desk logs the incident in ServiceNow.
2. The on-call Engineer investigates and updates the ticket every 2 hours.
3. The IT Service Desk informs the affected Customer when service is restored.

## Rules
Engineers must not deploy changes during an active Severity 1 incident. All Postmortem Reports should be reviewed by the Engineering Manager.
