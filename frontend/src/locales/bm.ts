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
  "nav.compliance_posture": "Postur Pematuhan",
  "nav.audit": "Log Audit",
  "nav.engines": "Aktiviti Enjin",
  "nav.settings": "Organisasi",
  "nav.help": "Pusat bantuan",
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

  // ──────────────────────────────────────────────────────────────────────
  // Marketing / landing surface — see en.ts for the canonical version.
  // ──────────────────────────────────────────────────────────────────────

  // Header
  "landing.header.nav.product": "Produk",
  "landing.header.nav.pricing": "Harga",
  "landing.header.nav.customers": "Pelanggan",
  "landing.header.nav.resources": "Sumber",
  "landing.header.signin": "Log masuk",
  "landing.header.cta": "Mula percubaan percuma",
  "landing.header.lang_label": "Bahasa",

  // Hero
  "landing.hero.live_pill": "Sedia untuk LHDN Fasa 4",
  "landing.hero.headline": "E-invois LHDN tanpa kerumitan.",
  "landing.hero.tagline_part1": "Lupakan PDF.",
  "landing.hero.tagline_part2": "Lupakan kunci.",
  "landing.hero.subhead":
    "PKS Malaysia menghadapi penalti sehingga RM 20,000 setiap invois yang tidak patuh mulai Januari 2027. ZeroKey menguruskan setiap invois — dari muat naik sehingga ke LHDN — dengan tepat, beraudit dan pantas.",
  "landing.hero.cta_primary": "Mula percubaan percuma",
  "landing.hero.cta_secondary": "Tempah demo",
  "landing.hero.trust.symprio": "Produk Symprio Sdn Bhd",
  "landing.hero.trust.mdec": "Diiktiraf MDEC",
  "landing.hero.trust.lhdn": "Perantara perisian berdaftar LHDN",

  // Section H2s
  "landing.problem.headline":
    "Mulai Januari 2027, setiap invois yang tidak patuh ada harganya.",
  "landing.howitworks.headline_a": "Daripada PDF ke penghantaran LHDN yang disahkan, ",
  "landing.howitworks.headline_em": "tanpa menaip",
  "landing.trust.headline_a": "Dibina pada piawaian BFSI. ",
  "landing.trust.headline_em": "Dijual untuk PKS.",
  "landing.pricing.headline": "Harga yang sesuai dengan jumlah invois sebenar anda.",
  "landing.pricing.sub":
    "Semua pelan termasuk penghantaran LHDN MyInvois. Percubaan percuma tanpa kad kredit. Tukar pelan bila-bila masa.",
  "landing.pricing.note":
    "Semua harga dalam MYR. Jaminan pulangan wang 30 hari. Bil tahunan menjimatkan 15%.",
  "landing.faq.headline": "Soalan lazim",
  "landing.whyzerokey.headline_a": "Tiga pilihan, tiga tukar-tukar. ",
  "landing.whyzerokey.headline_em": "Inilah tempat kami.",
  "landing.builtformy.eyebrow": "Dibina untuk perniagaan Malaysia",
  "landing.builtformy.headline_a": "Bukan produk antarabangsa yang diterjemah. ",
  "landing.builtformy.headline_em": "Buatan Malaysia.",
  "landing.builtformy.sub":
    "MyInvois mempunyai keperluan berbentuk Malaysia. Kod MSIC, tetingkap pembatalan, bahasa serantau, sistem perakaunan tempatan. Kami mulakan dari situ.",
  "landing.personas.headline_a": "Kasut berbeza, ",
  "landing.personas.headline_em": "pengawal selia yang sama.",
  "landing.personas.sub":
    "Di mana sahaja anda berada dalam aliran invois, inilah cara kami bekerjasama dengan anda.",

  // Final CTA
  "landing.cta_final.headline": "Berhenti bimbang tentang musim e-invois.",
  "landing.cta_final.sub":
    "Lepaskan satu PDF. Kami tandatangan, hantar dan jejak. Pasukan anda kekal pada kerja harian.",
  "landing.cta_final.cta_primary": "Mula percubaan percuma",
  "landing.cta_final.cta_secondary": "Tempah demo",
  "landing.cta_final.note": "Percubaan percuma 14 hari. Tiada kad kredit. Batal bila-bila masa.",

  // Footer
  "landing.footer.col.product": "Produk",
  "landing.footer.col.resources": "Sumber",
  "landing.footer.col.company": "Syarikat",
  "landing.footer.col.legal": "Undang-undang",
  "landing.footer.parent": "Produk Symprio Sdn Bhd",
  "landing.footer.copyright": "© {year} Symprio Sdn Bhd. Hak cipta terpelihara.",
};

export default bm;
