// 简体中文 (zh-MY) translation table.
//
// Keys missing from this table fall back to English. Marketing-surface
// translations cover the home page's high-visibility strings — section
// bodies, marketing detail pages, and legal pages are intentionally left
// to fall back to English pending a qualified translator pass.

const zh: Record<string, string> = {
  // Navigation (AppShell sidebar)
  "nav.dashboard": "仪表板",
  "nav.inbox": "收件箱",
  "nav.invoices": "发票",
  "nav.approvals": "审批",
  "nav.customers": "客户",
  "nav.items": "项目",
  "nav.connectors": "连接器",
  "nav.compliance_posture": "合规态势",
  "nav.audit": "审计日志",
  "nav.engines": "引擎活动",
  "nav.settings": "组织",
  "nav.help": "帮助中心",
  "nav.workflow": "工作流程",
  "nav.compliance": "合规",
  "nav.settings_group": "设置",
  "nav.signout": "登出",

  // Common actions
  "action.save": "保存修正",
  "action.discard": "丢弃",
  "action.upload": "上传",
  "action.cancel": "取消",
  "action.confirm": "确认",
  "action.dropFirst": "上传您的第一张发票 →",

  // Auth
  "auth.signin.title": "登录",
  "auth.signin.email": "电子邮件",
  "auth.signin.password": "密码",
  "auth.signin.submit": "登录",
  "auth.signin.error": "电子邮件或密码无效。",

  // Settings — language picker
  "settings.language.title": "语言",
  "settings.language.helper":
    "选择您希望在 ZeroKey 中看到的语言。数据本身不会被翻译。",

  // ──────────────────────────────────────────────────────────────────────
  // Marketing / landing surface
  // ──────────────────────────────────────────────────────────────────────

  // Header
  "landing.header.nav.product": "产品",
  "landing.header.nav.pricing": "价格",
  "landing.header.nav.customers": "客户",
  "landing.header.nav.resources": "资源",
  "landing.header.signin": "登录",
  "landing.header.cta": "Windows 下载",
  "landing.header.lang_label": "语言",

  // Hero
  "landing.hero.live_pill": "全新:ZeroKey 现已成为桌面应用",
  "landing.hero.headline": "LHDN 电子发票,从此不再头痛。",
  "landing.hero.tagline_part1": "告别 PDF。",
  "landing.hero.tagline_part2": "告别密钥。",
  "landing.hero.subhead":
    "将 ZeroKey 安装到您的 Windows 电脑。发票数据永不离开您的机器。每家公司一份年度许可证 — 由 Symprio 代您签名并提交至 LHDN,或您也可使用自己的证书。自 2027 年 1 月起,不合规发票将面临罚款。",
  "landing.hero.cta_primary": "Windows 下载",
  "landing.hero.cta_secondary": "联系我们",
  "landing.hero.trust.symprio": "Symprio Sdn Bhd 产品",
  "landing.hero.trust.mdec": "MDEC 认证",
  "landing.hero.trust.lhdn": "LHDN 注册软件中介",

  // Section H2s
  "landing.problem.headline":
    "自 2027 年 1 月起,每张不合规的发票都有一个价格。",
  "landing.howitworks.headline_a": "从 PDF 到经过验证的 LHDN 提交,",
  "landing.howitworks.headline_em": "无需输入",
  "landing.trust.headline_a": "按 BFSI 标准打造。",
  "landing.trust.headline_em": "为中小企业而生。",
  "landing.pricing.headline": "每家公司一份许可证。每年支付一次。",
  "landing.pricing.sub":
    "所有套餐均包含 LHDN MyInvois 提交,以及 30 天离线宽限期。桌面应用支持 Windows。无订阅、无按张计费。",
  "landing.pricing.note":
    "所有价格以 MYR 为单位,按年付费。30 天退款保证。许可证可随时转移至新机器。",
  "landing.faq.headline": "常见问题",
  "landing.whyzerokey.headline_a": "三个选择,三种取舍。",
  "landing.whyzerokey.headline_em": "这就是我们的位置。",
  "landing.builtformy.eyebrow": "为马来西亚企业而建",
  "landing.builtformy.headline_a": "不是翻译过来的国际产品。",
  "landing.builtformy.headline_em": "马来西亚制造。",
  "landing.builtformy.sub":
    "MyInvois 有马来西亚特色的要求。MSIC 代码、取消窗口、地区语言、本地会计系统。我们从这些出发。",
  "landing.personas.headline_a": "不同的角色,",
  "landing.personas.headline_em": "同一个监管机构。",
  "landing.personas.sub":
    "无论您在发票流程中的哪一端,这就是与我们合作的方式。",

  // Final CTA
  "landing.cta_final.headline": "别再害怕电子发票季节。",
  "landing.cta_final.sub":
    "安装到您的电脑。发票数据留在本机。一份年度许可证,包含 LHDN 提交。",
  "landing.cta_final.cta_primary": "Windows 下载",
  "landing.cta_final.cta_secondary": "联系我们",
  "landing.cta_final.note": "每家公司一份年度许可证。30 天退款保证。",

  // Footer
  "landing.footer.col.product": "产品",
  "landing.footer.col.resources": "资源",
  "landing.footer.col.company": "公司",
  "landing.footer.col.legal": "法律",
  "landing.footer.parent": "Symprio Sdn Bhd 产品",
  "landing.footer.copyright": "© {year} Symprio Sdn Bhd。版权所有。",
};

export default zh;
