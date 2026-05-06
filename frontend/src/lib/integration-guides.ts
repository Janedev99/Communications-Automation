export type IntegrationGuideId =
  | "postgres"
  | "llm"
  | "email_provider"
  | "notifications";

export interface GuideStep {
  title: string;
  body: string;
  envVar?: string;
  envExample?: string;
  link?: { label: string; href: string };
  code?: string;
  note?: string;
}

export interface GuidePath {
  id: string;
  label: string;
  description: string;
  steps: GuideStep[];
}

export interface IntegrationGuide {
  id: IntegrationGuideId;
  title: string;
  intro: string;
  whoSetsThisUp?: string;
  steps?: GuideStep[];
  paths?: GuidePath[];
  commonIssues: { problem: string; fix: string }[];
  verify: string;
}

export const INTEGRATION_GUIDES: Record<IntegrationGuideId, IntegrationGuide> = {
  postgres: {
    id: "postgres",
    title: "Database (PostgreSQL)",
    intro:
      "This is the firm's database. Every email, draft, escalation, knowledge entry, and audit log lives here. If it's down, the whole portal stops working — but you almost never need to touch it directly.",
    whoSetsThisUp:
      "Your hosting provider (Railway, Supabase, etc.) manages the database itself. You only need the connection string from their dashboard.",
    steps: [
      {
        title: "Find your database in the hosting dashboard",
        body: "Log in to whoever hosts the portal (most likely Railway). Open the project, find the PostgreSQL service. The dashboard will show whether it's running or paused.",
        link: { label: "Open Railway", href: "https://railway.app/dashboard" },
      },
      {
        title: "Copy the connection string",
        body: "Inside the database service, look for a value labeled \"DATABASE_URL\" or \"Connection String\". It looks like postgresql://user:password@host:port/database. Copy the whole thing.",
      },
      {
        title: "Paste it into the portal's environment",
        body: "In the portal's hosting environment (Railway → portal service → Variables), set the variable below to the connection string you just copied. Save and let the portal redeploy.",
        envVar: "DATABASE_URL",
        envExample: "postgresql://user:pass@host:5432/jane_automation",
      },
      {
        title: "Confirm backups are enabled",
        body: "On Railway, daily backups are enabled by default on paid plans. Other hosts may require you to turn this on manually. Confirm with your host that automatic daily backups are running before going live.",
      },
    ],
    commonIssues: [
      {
        problem: "Status shows \"Down\"",
        fix: "Open the database service in your host's dashboard. The most common cause is the database being paused (free-tier hosts pause inactive databases). Resume it, then refresh this page.",
      },
      {
        problem: "Status shows \"Down\" with an SSL error",
        fix: "Some hosts require ?sslmode=require at the end of the connection string. Add it if it's missing.",
      },
      {
        problem: "Latency is over 500ms",
        fix: "Your database might be in a different region than the portal. Move them to the same region in your host's dashboard.",
      },
    ],
    verify:
      "After saving the connection string and letting the portal redeploy, the status pill on this card should turn green within a minute.",
  },

  llm: {
    id: "llm",
    title: "AI provider",
    intro:
      "The AI that reads incoming emails, decides which category they belong to, and drafts the suggested replies. Without it the portal falls back to keyword-based rules. Two paths are supported: Anthropic Claude (cloud, simplest setup) and an OpenAI-compatible endpoint like RunPod (self-hosted, keeps client data on rented hardware).",
    whoSetsThisUp:
      "Anthropic: anyone with admin access to a credit card — about 5 minutes total. RunPod: someone comfortable provisioning a serverless GPU endpoint (or your IT contractor / Gar). Either way, the cutover is just a few environment variables.",
    paths: [
      {
        id: "anthropic",
        label: "Anthropic Claude",
        description:
          "Cloud-hosted, pay-as-you-go. Simplest path; the firm's data passes through Anthropic's servers (covered by their commercial terms — they don't train on it).",
        steps: [
          {
            title: "Create an Anthropic account",
            body: "Go to console.anthropic.com and sign up if you don't have an account already. Add a payment method — Claude is pay-as-you-go, typically a few dollars a month for a small firm.",
            link: { label: "Open Anthropic Console", href: "https://console.anthropic.com" },
          },
          {
            title: "Generate an API key",
            body: "In the console, go to Settings → API Keys → Create Key. Give it a name like \"Jane Portal\". Copy the key immediately — it starts with sk-ant- and you won't be able to see it again after closing the dialog.",
          },
          {
            title: "Set the provider env vars",
            body: "In your hosting environment (Railway → portal service → Variables), set both variables below. Save.",
            envVar: "LLM_PROVIDER",
            envExample: "anthropic",
            note:
              "Also set ANTHROPIC_API_KEY=sk-ant-api03-... (the key you just copied).",
          },
          {
            title: "(Optional) Set a daily spending cap",
            body: "Set a daily token budget — once hit, the portal stops calling Claude for the rest of the day and falls back to rules. Default is 1,000,000 tokens (~$3-15 depending on model). Lower for safety while piloting.",
            envVar: "DAILY_TOKEN_BUDGET",
            envExample: "500000",
          },
        ],
      },
      {
        id: "openai_compat",
        label: "RunPod (self-hosted)",
        description:
          "A Gemma model running on rented GPU hardware via vLLM, exposed through an OpenAI-compatible API. Client data stays inside the firm's rented hardware. Approved on the 05/02 product call.",
        steps: [
          {
            title: "Provision a vLLM endpoint on RunPod",
            body: "On runpod.io, create a serverless endpoint using their vLLM template. Choose the Gemma model size that fits your budget (e.g. google/gemma-2-27b-it). RunPod gives you an endpoint id like 'abc12345'.",
            link: { label: "Open RunPod", href: "https://www.runpod.io/console/serverless" },
          },
          {
            title: "Generate a RunPod API key",
            body: "Settings → API Keys → Create. Copy it — you'll paste it as LLM_API_KEY below.",
          },
          {
            title: "Set the provider env vars",
            body: "In your hosting environment, set the four variables below. The base URL pattern is https://api.runpod.ai/v2/<endpoint-id>/openai/v1.",
            envVar: "LLM_PROVIDER",
            envExample: "openai_compat",
            note:
              "Also set: LLM_API_KEY=<runpod-key>, LLM_BASE_URL=https://api.runpod.ai/v2/<id>/openai/v1, LLM_MODEL=google/gemma-2-27b-it (or whichever model you deployed).",
          },
          {
            title: "Restart the portal",
            body: "Save your environment variables and let the portal redeploy (about 60 seconds). This card should flip to Healthy after the next email is processed.",
          },
        ],
      },
    ],
    commonIssues: [
      {
        problem: "Status shows \"Not configured\" with API key \"placeholder\" (Anthropic path)",
        fix: "The portal is running with the demo placeholder key. Replace ANTHROPIC_API_KEY with a real key from console.anthropic.com.",
      },
      {
        problem: "Status shows \"Not configured\" with last_error mentioning LLM_API_KEY or LLM_BASE_URL",
        fix: "LLM_PROVIDER=openai_compat but at least one of LLM_API_KEY / LLM_BASE_URL is empty. Fill them in (RunPod console for the key, the endpoint URL pattern is in the docs).",
      },
      {
        problem: "Drafts stopped generating mid-day, status shows \"Degraded\"",
        fix: "You probably hit the daily token budget (Anthropic) or the RunPod endpoint went cold. Check \"Budget used\" on the card and the RunPod console respectively.",
      },
      {
        problem: "Status shows \"Healthy\" but no drafts are appearing on emails",
        fix: "Check the Audit Log page for draft generation errors. The most common causes are a billing issue on the upstream account, or SHADOW_MODE=true / DRAFT_AUTO_GENERATE=false in the portal config.",
      },
    ],
    verify:
      "Once the provider env vars are set, the status pill turns green and \"Tokens today\" updates as new emails come in. You can also re-categorize any email manually to force a fresh LLM call.",
  },

  email_provider: {
    id: "email_provider",
    title: "Email Provider",
    intro:
      "This is how the portal reads incoming client emails and sends approved replies back out. There are two ways to connect — Microsoft Graph (recommended for Microsoft 365 / Outlook business accounts) or IMAP/SMTP (works with Gmail, free Outlook, or any standard mailbox).",
    whoSetsThisUp:
      "Microsoft Graph requires a Microsoft 365 admin to register an app in Azure — if your firm has an IT contractor, give them this checklist. IMAP setup can be done by anyone with the mailbox password.",
    paths: [
      {
        id: "msgraph",
        label: "Microsoft 365 (Graph)",
        description:
          "Recommended for firms on Microsoft 365 / Outlook business. Doesn't need the mailbox password — uses an Azure app registration with delegated permission to a single mailbox.",
        steps: [
          {
            title: "Open the Azure portal as an admin",
            body: "Sign in to portal.azure.com with a Microsoft 365 admin account. Search for \"App registrations\" and open it.",
            link: { label: "Open Azure Portal", href: "https://portal.azure.com" },
            note: "If you don't have admin access, ask your IT contractor to do steps 1–5 — they take about 10 minutes.",
          },
          {
            title: "Register a new app",
            body: "Click \"New registration\". Name it \"Jane Email Portal\" (or anything you like). Account type: \"Single tenant\". Leave redirect URI blank. Register.",
          },
          {
            title: "Add mailbox permissions",
            body: "In the new app, go to \"API permissions\" → Add a permission → Microsoft Graph → Application permissions. Add: Mail.Read, Mail.Send, Mail.ReadWrite. Then click \"Grant admin consent\" — without this, the portal can't read mail.",
          },
          {
            title: "Create a client secret",
            body: "Go to \"Certificates & secrets\" → New client secret. Set expiry to 24 months. Copy the secret value immediately — it's only shown once. You'll also need the Application (client) ID and Directory (tenant) ID from the app's Overview page.",
          },
          {
            title: "Paste the four values into the portal's environment",
            body: "In your hosting environment (Railway → portal service → Variables), set all four variables. Save.",
            code: "EMAIL_PROVIDER=msgraph\nMSGRAPH_TENANT_ID=<directory-tenant-id>\nMSGRAPH_CLIENT_ID=<application-client-id>\nMSGRAPH_CLIENT_SECRET=<the-secret-value>\nMSGRAPH_MAILBOX=jane@yourfirm.com",
          },
          {
            title: "Wait for the next poll",
            body: "The portal polls every 60 seconds. Within a minute or two of the redeploy finishing, the status pill should flip to Healthy and \"Last success\" should update. New emails will start appearing in the Emails page.",
          },
        ],
      },
      {
        id: "imap",
        label: "IMAP / SMTP",
        description:
          "Works with Gmail, free Outlook, Fastmail, and most other providers. Uses the mailbox password (or app password) directly. Easiest to set up but less secure than the Graph option.",
        steps: [
          {
            title: "Generate an app password",
            body: "If your provider has 2FA (most do — Gmail, Outlook, Yahoo), you need an app password instead of your real password. Look for \"App passwords\" in your account's security settings. Generate one for \"Jane Portal\" and copy the 16-character code.",
            link: { label: "Gmail app passwords", href: "https://myaccount.google.com/apppasswords" },
          },
          {
            title: "Find your IMAP and SMTP servers",
            body: "Search for your provider's IMAP/SMTP settings. Common ones: Gmail → imap.gmail.com:993 / smtp.gmail.com:587. Outlook (free) → outlook.office365.com:993 / smtp-mail.outlook.com:587.",
          },
          {
            title: "Paste the values into the portal's environment",
            body: "In your hosting environment (Railway → portal service → Variables), set all the variables below. Save.",
            code: "EMAIL_PROVIDER=imap\nIMAP_HOST=imap.gmail.com\nIMAP_PORT=993\nIMAP_USERNAME=jane@yourfirm.com\nIMAP_PASSWORD=<app-password-from-step-1>\nSMTP_HOST=smtp.gmail.com\nSMTP_PORT=587\nSMTP_USERNAME=jane@yourfirm.com\nSMTP_PASSWORD=<app-password-from-step-1>",
          },
          {
            title: "Wait for the next poll",
            body: "The portal polls every 60 seconds. Within a minute or two, the status pill should flip to Healthy and new emails will start appearing.",
          },
        ],
      },
    ],
    commonIssues: [
      {
        problem: "Status \"Down\" — \"Authentication failed\"",
        fix: "For IMAP: you used your real password instead of an app password. Generate an app password from your provider's security settings. For Graph: the client secret expired or admin consent was never granted — re-create the secret and click \"Grant admin consent\" in Azure.",
      },
      {
        problem: "Status \"Degraded\" — \"No successful poll in the last X minutes\"",
        fix: "The portal hasn't completed a polling cycle. Most likely cause: it's still starting up after a redeploy (wait 1–2 minutes), or the mailbox is empty so nothing is being processed (send a test email).",
      },
      {
        problem: "Emails arrive but no drafts are generated",
        fix: "That means the email provider is fine, but the AI is unavailable. Check the AI provider card above — it's probably not configured (Anthropic key missing, or RunPod base URL not set), or out of budget.",
      },
    ],
    verify:
      "Send a test email to the configured mailbox. Within 60 seconds, it should appear in the Emails page with an AI category and a draft reply (assuming the AI provider is also configured).",
  },

  notifications: {
    id: "notifications",
    title: "Notifications",
    intro:
      "When something needs Jane's attention immediately — an IRS notice, a complaint, a system error — the portal pings a Slack channel or writes to a log file. Not strictly required, but strongly recommended so urgent items aren't missed.",
    whoSetsThisUp:
      "If your firm uses Slack, anyone who can install apps in your workspace. Otherwise the log file path is fine and works out of the box.",
    steps: [
      {
        title: "Choose Slack or log file",
        body: "Slack is much better — alerts pop up in real time on phones and desktops. Log file is a fallback if your firm doesn't use Slack: events are appended to a text file the admin can review.",
      },
      {
        title: "(Slack) Create an Incoming Webhook",
        body: "Open the Slack apps directory and add \"Incoming Webhooks\". Choose the channel where alerts should go (e.g. #jane-alerts), then copy the webhook URL. It looks like https://hooks.slack.com/services/T.../B.../...",
        link: { label: "Slack Incoming Webhooks", href: "https://my.slack.com/apps/A0F7XDUAZ-incoming-webhooks" },
      },
      {
        title: "(Slack) Paste the webhook URL into the portal",
        body: "In your hosting environment, set the variable below to the webhook URL. Save.",
        envVar: "SLACK_WEBHOOK_URL",
        envExample: "https://hooks.slack.com/services/T0.../B0.../...",
      },
      {
        title: "(Log file alternative) Set the log path",
        body: "If you're not using Slack, set this to a writable file path on the server. The portal will append a JSON line for every notification. Default is to write to stdout, which you can read in your hosting provider's logs view.",
        envVar: "NOTIFY_LOG_FILE",
        envExample: "/var/log/jane-notifications.log",
      },
    ],
    commonIssues: [
      {
        problem: "Status \"Healthy\" but no Slack messages arrive",
        fix: "The webhook might have been revoked, or the channel was deleted. Generate a new webhook URL in Slack and update SLACK_WEBHOOK_URL.",
      },
      {
        problem: "Status \"Not configured\"",
        fix: "Neither SLACK_WEBHOOK_URL nor NOTIFY_LOG_FILE is set. Set at least one — they can both be enabled at the same time if you want belt-and-suspenders.",
      },
    ],
    verify:
      "Trigger a test escalation by re-categorizing any email as a complaint (or IRS notice). Within seconds, you should see a message in your Slack channel — or a new line in the log file.",
  },
};
