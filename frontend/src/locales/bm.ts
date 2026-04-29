// Bahasa Malaysia (bm-MY) translation table — Slice 86.
//
// Keys missing from this table fall back to the English table.
// Translations were drafted with attention to the SME / accounting
// audience — same register an AutoCount or SQL Accounting user
// would expect, not formal/literary BM.

const bm: Record<string, string> = {
  // Navigation
  "nav.dashboard": "Papan Pemuka",
  "nav.inbox": "Peti Masuk",
  "nav.invoices": "Invois",
  "nav.approvals": "Kelulusan",
  "nav.customers": "Pelanggan",
  "nav.items": "Barang",
  "nav.connectors": "Penyambung",
  "nav.audit": "Log Audit",
  "nav.engines": "Aktiviti Enjin",
  "nav.settings": "Organisasi",
  "nav.workflow": "Aliran Kerja",
  "nav.compliance": "Pematuhan",
  "nav.settings_group": "Tetapan",
  "nav.signout": "Log keluar",

  // Dashboard
  "dashboard.title": "Papan Pemuka",
  "dashboard.recent_uploads": "Muat naik terkini",
  "dashboard.empty.title": "Tiada invois lagi",
  "dashboard.empty.body":
    "Lepaskan invois pertama anda — PDF, imej, Excel — untuk lihat ia mendarat di sini.",

  // Customers
  "customers.title": "Pelanggan",
  "customers.subtitle": "Pembeli yang ZeroKey pelajari daripada invois anda",
  "customers.count": "{count} jumlah",
  "customers.empty.title": "Tiada pelanggan lagi",
  "customers.empty.body":
    "Pelanggan muncul di sini secara automatik apabila anda menghantar invois. Setiap pembeli baru yang dibaca ZeroKey mencipta rekod induk; invois berikutnya untuk pembeli itu diisi automatik daripada rekod ini.",

  // Items
  "items.title": "Barang",
  "items.subtitle": "Penerangan baris item yang ZeroKey pelajari daripada invois anda",
  "items.empty.title": "Tiada barang lagi",

  // Common actions
  "action.save": "Simpan pembetulan",
  "action.discard": "Buang",
  "action.upload": "Muat naik",
  "action.cancel": "Batal",
  "action.confirm": "Sahkan",
  "action.dropFirst": "Lepaskan invois pertama anda →",

  // Auth
  "auth.signin.title": "Log masuk",
  "auth.signin.email": "E-mel",
  "auth.signin.password": "Kata laluan",
  "auth.signin.submit": "Log masuk",
  "auth.signin.error": "E-mel atau kata laluan tidak sah.",

  // Settings — language picker
  "settings.language.title": "Bahasa",
  "settings.language.helper":
    "Pilih bahasa yang anda mahu lihat ZeroKey. Data itu sendiri tidak diterjemahkan.",
};

export default bm;
