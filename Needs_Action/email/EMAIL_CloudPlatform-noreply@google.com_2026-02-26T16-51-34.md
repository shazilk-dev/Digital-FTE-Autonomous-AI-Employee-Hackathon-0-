---
has_attachments: false
labels:
- UNREAD
- IMPORTANT
- CATEGORY_UPDATES
- INBOX
message_id: 19c6be43c5750345
priority: high
received: '2026-02-17T05:57:25-08:00'
requires_approval: false
sender_email: CloudPlatform-noreply@google.com
source: Google Cloud <CloudPlatform-noreply@google.com>
status: pending
subject: '[Action Required] Upgrade Cloud Functions for Firebase configuration by
  Mar 31, 2027'
thread_id: 19c6be43c5750345
type: email
---

## Email Content

Hello Shazil,

You’re receiving this communication because we’re retiring the legacy  
environment configuration feature for Cloud Functions for Firebase (1st  
gen). To ensure seamless deployments and enhanced security, you will need  
to migrate your deployment to Secret Manager.

We’ve provided additional information below to guide you through this  
change.

What you need to know

Key changes:

    - We’re retiring the legacy Cloud Functions for Firebase configuration  
feature, which relies on the Google Cloud Deployment Manager[1].
    - We’re transitioning to Secret Manager[2] for sensitive configurations  
and standard environment variables for non-sensitive ones. This aligns our  
practices with the security standards used in Cloud Functions for  
Firebase[3] (2nd gen).

Potential impact:

    - Existing Cloud Functions: Your currently deployed Cloud Functions for  
Firebase will continue to run without interruption.
    - New Deployments: After March 31, 2027, you will not be able to deploy  
updates to Cloud Functions for Firebase that rely on the legacy Cloud  
Runtime Configuration API.
    - Data Access: After March 31, 2027, the underlying Runtime  
Configuration API[4] will be inaccessible for all Firebase users. You must  
export your data before this deadline to avoid potential data loss.
    - Cost: Most users will experience no change in cost.Storing  
non-sensitive configuration in .env files is free. Secret Manager provides  
a free tier of six active secret versions for sensitive data, which should  
cover most projects.

What you need to do

Action required:

To ensure seamless deployments and enhanced security, please take the  
following steps to migrate your configuration:

    1. Export your configuration: Update to the latest Firebase Command Line  
Interface (CLI) and run the Firebase functions:config:export command. The  
tool will automatically format your existing data for Secret Manager. 

## Metadata

- **From:** Google Cloud <CloudPlatform-noreply@google.com>
- **To:** shazil.akn@gmail.com
- **Date:** 2026-02-17T05:57:25-08:00
- **Attachments:** None

## Suggested Actions

- [ ] Reply to sender
- [ ] Forward to relevant party
- [ ] Flag for follow-up
- [ ] Archive after processing
