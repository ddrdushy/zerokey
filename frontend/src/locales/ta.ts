// தமிழ் (ta-MY) translation table.
//
// Keys missing from this table fall back to English. Tamil is a first-class
// language for ZeroKey per BRAND_KIT.md — the founder's heritage language
// and a marker of authenticity for the Tamil-speaking SME segment.
//
// Translations cover the home page's high-visibility strings. Section
// bodies, marketing detail pages, and legal pages currently fall back to
// English pending a qualified Tamil translator pass — placeholder is
// better than a poor translation in a first-class language.

const ta: Record<string, string> = {
  // Navigation
  "nav.dashboard": "டாஷ்போர்டு",
  "nav.inbox": "உள்வரும்",
  "nav.invoices": "விலைப்பட்டியல்கள்",
  "nav.approvals": "ஒப்புதல்கள்",
  "nav.customers": "வாடிக்கையாளர்கள்",
  "nav.items": "உருப்படிகள்",
  "nav.connectors": "இணைப்பான்கள்",
  "nav.compliance_posture": "இணக்க நிலை",
  "nav.audit": "தணிக்கை பதிவு",
  "nav.engines": "என்ஜின் செயல்பாடு",
  "nav.settings": "நிறுவனம்",
  "nav.help": "உதவி மையம்",
  "nav.workflow": "பணிப்பாய்வு",
  "nav.compliance": "இணக்கம்",
  "nav.settings_group": "அமைப்புகள்",
  "nav.signout": "வெளியேறு",

  // Common actions
  "action.save": "திருத்தங்களை சேமி",
  "action.discard": "நிராகரி",
  "action.upload": "பதிவேற்று",
  "action.cancel": "ரத்து செய்",
  "action.confirm": "உறுதிப்படுத்து",
  "action.dropFirst": "உங்கள் முதல் விலைப்பட்டியலை பதிவேற்றவும் →",

  // Auth
  "auth.signin.title": "உள்நுழை",
  "auth.signin.email": "மின்னஞ்சல்",
  "auth.signin.password": "கடவுச்சொல்",
  "auth.signin.submit": "உள்நுழை",
  "auth.signin.error": "தவறான மின்னஞ்சல் அல்லது கடவுச்சொல்.",

  // Settings — language picker
  "settings.language.title": "மொழி",
  "settings.language.helper":
    "ZeroKey-ஐ நீங்கள் பார்க்க விரும்பும் மொழியை தேர்வு செய்யவும். தரவு மொழிபெயர்க்கப்படுவதில்லை.",

  // ──────────────────────────────────────────────────────────────────────
  // Marketing / landing surface
  // ──────────────────────────────────────────────────────────────────────

  // Header
  "landing.header.nav.product": "தயாரிப்பு",
  "landing.header.nav.pricing": "விலை",
  "landing.header.nav.customers": "வாடிக்கையாளர்கள்",
  "landing.header.nav.resources": "வளங்கள்",
  "landing.header.signin": "உள்நுழை",
  "landing.header.cta": "இலவச சோதனையை தொடங்கு",
  "landing.header.lang_label": "மொழி",

  // Hero
  "landing.hero.live_pill": "LHDN கட்டம் 4 சேவையில்",
  "landing.hero.headline": "தலைவலி இல்லாமல் LHDN இ-இன்வாய்சிங்.",
  "landing.hero.tagline_part1": "PDF-ஐ விட்டுவிடுங்கள்.",
  "landing.hero.tagline_part2": "சாவிகளை விட்டுவிடுங்கள்.",
  "landing.hero.subhead":
    "ஜனவரி 2027 முதல், மலேசிய SME-கள் ஒவ்வொரு பொருந்தாத விலைப்பட்டியலுக்கும் RM 20,000 வரை அபராதம் எதிர்கொள்கின்றன. ZeroKey ஒவ்வொரு விலைப்பட்டியலையும் பதிவேற்றத்திலிருந்து LHDN வரை கையாளுகிறது — துல்லியமாக, தணிக்கை செய்யப்பட்டு, விரைவாக.",
  "landing.hero.cta_primary": "இலவச சோதனையை தொடங்கு",
  "landing.hero.cta_secondary": "டெமோ முன்பதிவு செய்",
  "landing.hero.trust.symprio": "Symprio Sdn Bhd-ன் தயாரிப்பு",
  "landing.hero.trust.mdec": "MDEC அங்கீகாரம் பெற்றது",
  "landing.hero.trust.lhdn": "LHDN பதிவு செய்யப்பட்ட மென்பொருள் இடைத்தரகர்",

  // Section H2s
  "landing.problem.headline":
    "ஜனவரி 2027 முதல், ஒவ்வொரு பொருந்தாத விலைப்பட்டியலுக்கும் ஒரு விலை உண்டு.",
  "landing.howitworks.headline_a": "PDF-லிருந்து சரிபார்க்கப்பட்ட LHDN சமர்ப்பிப்பு வரை, ",
  "landing.howitworks.headline_em": "தட்டச்சு செய்யாமல்",
  "landing.trust.headline_a": "BFSI தரத்தில் கட்டப்பட்டது. ",
  "landing.trust.headline_em": "SME-க்களுக்கு விற்கப்படுகிறது.",
  "landing.pricing.headline": "நீங்கள் உண்மையில் அனுப்பும் விலைப்பட்டியல்களுக்கு பொருத்தமான விலை.",
  "landing.pricing.sub":
    "அனைத்து திட்டங்களிலும் LHDN MyInvois சமர்ப்பிப்பு உள்ளது. இலவச சோதனைக்கு கிரெடிட் கார்டு தேவையில்லை. எந்த நேரத்திலும் திட்டத்தை மாற்றலாம்.",
  "landing.pricing.note":
    "அனைத்து விலைகளும் MYR-ல். 30 நாள் பணம் திரும்பும் உத்தரவாதம். வருடாந்திர பில் 15% சேமிக்கிறது.",
  "landing.faq.headline": "அடிக்கடி கேட்கப்படும் கேள்விகள்",
  "landing.whyzerokey.headline_a": "மூன்று மாற்றுகள், மூன்று சமரசங்கள். ",
  "landing.whyzerokey.headline_em": "இதோ எங்கள் இடம்.",
  "landing.builtformy.eyebrow": "மலேசிய வணிகங்களுக்காக கட்டப்பட்டது",
  "landing.builtformy.headline_a": "மொழிபெயர்க்கப்பட்ட சர்வதேச தயாரிப்பு அல்ல. ",
  "landing.builtformy.headline_em": "மலேசியாவை சேர்ந்தது.",
  "landing.builtformy.sub":
    "MyInvois-க்கு மலேசிய தேவைகள் உள்ளன. MSIC குறியீடுகள், ரத்து சாளரம், பிராந்திய மொழிகள், உள்ளூர் கணக்கியல் முறைகள். நாங்கள் அங்கிருந்தே தொடங்கினோம்.",
  "landing.personas.headline_a": "வெவ்வேறு பாத்திரங்கள், ",
  "landing.personas.headline_em": "ஒரே கட்டுப்பாட்டாளர்.",
  "landing.personas.sub":
    "விலைப்பட்டியல் பாய்வில் நீங்கள் எங்கிருந்தாலும், எங்களுடன் வேலை செய்யும் வடிவம் இதுதான்.",

  // Final CTA
  "landing.cta_final.headline": "இ-இன்வாய்சிங் காலத்தை பற்றி பயப்படுவதை நிறுத்துங்கள்.",
  "landing.cta_final.sub":
    "ஒரு PDF-ஐ பதிவேற்றுங்கள். நாங்கள் கையெழுத்திடுவோம், சமர்ப்பிப்போம், கண்காணிப்போம். உங்கள் குழு தங்கள் வேலையை தொடரும்.",
  "landing.cta_final.cta_primary": "இலவச சோதனையை தொடங்கு",
  "landing.cta_final.cta_secondary": "டெமோ முன்பதிவு செய்",
  "landing.cta_final.note": "14 நாள் இலவச சோதனை. கிரெடிட் கார்டு தேவையில்லை. எந்த நேரத்திலும் ரத்து செய்யலாம்.",

  // Footer
  "landing.footer.col.product": "தயாரிப்பு",
  "landing.footer.col.resources": "வளங்கள்",
  "landing.footer.col.company": "நிறுவனம்",
  "landing.footer.col.legal": "சட்டம்",
  "landing.footer.parent": "Symprio Sdn Bhd-ன் தயாரிப்பு",
  "landing.footer.copyright": "© {year} Symprio Sdn Bhd. அனைத்து உரிமைகளும் பாதுகாக்கப்பட்டவை.",
};

export default ta;
