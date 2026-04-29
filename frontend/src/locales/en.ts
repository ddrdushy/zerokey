// English (en-MY) translation table — Slice 86.
//
// Keys are dot-namespaced by surface ("nav.*", "dashboard.*",
// "customers.*", etc.). New keys must land here first; the BM
// table is populated from this one.
//
// Variables in strings use `{name}` syntax — see translate() for
// substitution rules.

const en: Record<string, string> = {
  // Navigation (AppShell sidebar)
  "nav.dashboard": "Dashboard",
  "nav.inbox": "Inbox",
  "nav.invoices": "Invoices",
  "nav.customers": "Customers",
  "nav.items": "Items",
  "nav.connectors": "Connectors",
  "nav.audit": "Audit log",
  "nav.engines": "Engine activity",
  "nav.settings": "Organization",
  "nav.workflow": "Workflow",
  "nav.compliance": "Compliance",
  "nav.settings_group": "Settings",
  "nav.signout": "Sign out",

  // Dashboard
  "dashboard.title": "Dashboard",
  "dashboard.recent_uploads": "Recent uploads",
  "dashboard.empty.title": "No invoices yet",
  "dashboard.empty.body": "Drop your first invoice — PDF, image, Excel — to see it land here.",

  // Customers
  "customers.title": "Customers",
  "customers.subtitle": "Buyers ZeroKey has learned from your invoices",
  "customers.count": "{count} total",
  "customers.empty.title": "No customers yet",
  "customers.empty.body":
    "Customers appear here automatically as you submit invoices. Each new buyer ZeroKey reads creates a master record; subsequent invoices for that buyer auto-fill from it.",

  // Items
  "items.title": "Items",
  "items.subtitle": "Line-item descriptions ZeroKey has learned from your invoices",
  "items.empty.title": "No items yet",

  // Common actions
  "action.save": "Save corrections",
  "action.discard": "Discard",
  "action.upload": "Upload",
  "action.cancel": "Cancel",
  "action.confirm": "Confirm",
  "action.dropFirst": "Drop your first invoice →",

  // Auth
  "auth.signin.title": "Sign in",
  "auth.signin.email": "Email",
  "auth.signin.password": "Password",
  "auth.signin.submit": "Sign in",
  "auth.signin.error": "Invalid email or password.",

  // Settings — language picker
  "settings.language.title": "Language",
  "settings.language.helper":
    "Choose the language you'd like to see ZeroKey in. The data itself isn't translated.",
};

export default en;
