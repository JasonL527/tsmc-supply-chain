const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType,
  ShadingType, ExternalHyperlink, PageNumber, Header, Footer,
} = require("docx");

const ORANGE = "C2410C", INK = "1F2937", GREY = "6B7280", LINE = "D1D5DB";
const CONTENT_W = 9360;

const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const P = (runs, opts = {}) =>
  new Paragraph({ spacing: { after: 120 }, children: Array.isArray(runs) ? runs : [new TextRun(runs)], ...opts });
const t = (text, o = {}) => new TextRun({ text, ...o });
const bold = (text) => new TextRun({ text, bold: true });
const code = (text) => new TextRun({ text, font: "Courier New", size: 19, color: "B91C1C" });

function numbered(text, extra = []) {
  return new Paragraph({
    numbering: { reference: "steps", level: 0 }, spacing: { after: 100 },
    children: [t(text), ...extra],
  });
}
function bullet(children) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
    children: Array.isArray(children) ? children : [t(children)],
  });
}
function link(text, url) {
  return new ExternalHyperlink({ link: url, children: [new TextRun({ text, style: "Hyperlink" })] });
}
function callout(children) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [CONTENT_W],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: CONTENT_W, type: WidthType.DXA },
      shading: { fill: "FEF3C7", type: ShadingType.CLEAR },
      margins: { top: 120, bottom: 120, left: 160, right: 160 },
      borders: { left: { style: BorderStyle.SINGLE, size: 18, color: ORANGE },
        top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } },
      children: (Array.isArray(children) ? children : [children]),
    })] })],
  });
}
function codeBlock(lines) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [CONTENT_W],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: CONTENT_W, type: WidthType.DXA },
      shading: { fill: "0B101D", type: ShadingType.CLEAR },
      margins: { top: 120, bottom: 120, left: 160, right: 160 },
      borders: {},
      children: lines.map((l) => new Paragraph({ spacing: { after: 0 },
        children: [new TextRun({ text: l || " ", font: "Courier New", size: 18, color: "E8E9F3" })] })),
    })] })],
  });
}

const border = { style: BorderStyle.SINGLE, size: 1, color: LINE };
const borders = { top: border, bottom: border, left: border, right: border };
function cell(text, w, { head = false, fill } = {}) {
  return new TableCell({
    width: { size: w, type: WidthType.DXA }, borders,
    shading: fill ? { fill, type: ShadingType.CLEAR } : undefined,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({ children: [new TextRun({ text, bold: head, color: head ? "FFFFFF" : INK, size: 20 })] })],
  });
}
function costTable() {
  const ws = [2600, 2000, 1900, 2860];
  const row = (cells, opt = {}) => new TableRow({ children: cells.map((c, i) => cell(c, ws[i], opt)) });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: ws,
    rows: [
      new TableRow({ children: [
        cell("Service", ws[0], { head: true, fill: ORANGE }),
        cell("Free for your use?", ws[1], { head: true, fill: ORANGE }),
        cell("Card to start?", ws[2], { head: true, fill: ORANGE }),
        cell("Ongoing or one-time?", ws[3], { head: true, fill: ORANGE }),
      ] }),
      row(["Google Places", "Yes, in practice", "Yes", "Pay-as-you-go (~$0)"], { fill: "F9FAFB" }),
      row(["OpenCorporates", "Maybe not (commercial)", "If paid plan", "Ongoing if paid"]),
      row(["ImportYeti website (manual)", "Yes", "No", "$0"], { fill: "F9FAFB" }),
      row(["BoL API (ImportGenius / Panjiva / Trademo)", "No", "Yes", "Ongoing monthly"]),
    ],
  });
}

const doc = new Document({
  creator: "Project Sauron",
  styles: {
    default: { document: { run: { font: "Arial", size: 22, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, color: ORANGE, font: "Arial" },
        paragraph: { spacing: { before: 320, after: 140 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ORANGE, space: 4 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, color: INK, font: "Arial" },
        paragraph: { spacing: { before: 220, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "steps", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 360 } } } }] },
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 360 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Project Sauron — Setup Guide   ·   Page ", size: 16, color: GREY }),
        new TextRun({ children: [PageNumber.CURRENT], size: 16, color: GREY })] })] }) },
    children: [
      new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: "PROJECT SAURON", bold: true, size: 48, color: INK })] }),
      new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "Setup Guide — API Keys, Costs & Login", size: 26, color: ORANGE })] }),
      new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "How to switch on the live OSINT integrations and put the dashboard behind a login.", italics: true, color: GREY, size: 20 })] }),

      callout([
        P([bold("Read this first. "), t("The app already works without any of these keys — it just shows clearly-labelled mock/demo data for the OSINT tools. You only need the keys below to pull "), bold("live"), t(" data. Add them whenever you're ready; nothing breaks in the meantime.")], { spacing: { after: 0 } }),
      ]),
      P(" "),

      // ─────────────────────────────────────────────────────────────
      H1("1. Where the keys go (do this once)"),
      P([t("Every key, plus your login passwords, goes into one place called "), bold("Secrets"), t(" — a private settings box that is never uploaded to GitHub. You have two situations:")]),

      H2("A. The live website (Streamlit Community Cloud) — most important"),
      numbered("Go to ", [link("share.streamlit.io", "https://share.streamlit.io"), t(" and sign in. You'll see your app in the list.")]),
      numbered("Click the three-dot menu (⋮) next to the app, then click “Settings.”"),
      numbered("Open the “Secrets” tab. You'll see an empty text box."),
      numbered("Paste the whole block from Section 6 of this guide, fill in your values, and click “Save.”"),
      numbered("The app restarts itself in about a minute. Done."),

      H2("B. Running it on your own computer (optional)"),
      numbered("In the project folder, open the folder named “.streamlit” (create it if missing)."),
      numbered("Create a file inside it named exactly secrets.toml.", []),
      numbered("Paste the same block from Section 6 and save. This file is already git-ignored, so it will never be uploaded."),
      P(" "),

      // ─────────────────────────────────────────────────────────────
      H1("2. Turning on the username / password login"),
      P([t("The dashboard can sit behind a simple sign-in screen. It's controlled by the same Secrets box. Add a "), code("[passwords]"), t(" section — one line per person who should have access:")]),
      codeBlock([ "[passwords]", 'admin = "pick-a-strong-password"', 'investor = "another-password"' ]),
      P(" "),
      bullet([bold("Until"), t(" you add a "), code("[passwords]"), t(" section, the app is open to anyone with the link.")]),
      bullet([bold("After"), t(" you add it and save, visitors must sign in with one of the username/password pairs.")]),
      bullet([t("To add or remove people later, just edit the lines and save — no code changes needed.")]),
      callout([ P([bold("Honest note on strength. "), t("This is a basic gate — good for keeping casual visitors and search engines out of a private demo. It is not enterprise single-sign-on. Use long, unique passwords, and don't reuse a password you use elsewhere.")], { spacing: { after: 0 } }) ]),
      P(" "),

      // ─────────────────────────────────────────────────────────────
      H1("3. Google Maps / Places API key"),
      P([bold("What it does in the app: "), t("turns a company's country-level dot into its real, precise location on the map.")]),
      numbered("Go to ", [link("console.cloud.google.com", "https://console.cloud.google.com"), t(" and sign in with a Google account.")]),
      numbered("Top bar → “New Project” → name it (e.g. “Sauron”) → Create."),
      numbered("Left menu → “Billing” → link a billing account. A credit/debit card is required even for free usage (Google won't charge unless you exceed the free allowance)."),
      numbered("Left menu → “APIs & Services” → “Library” → search “Places API (New)” → Enable."),
      numbered("“APIs & Services” → “Credentials” → “Create credentials” → “API key.” Copy the key it shows you."),
      numbered("Recommended: click the new key → “Restrict key” → under API restrictions choose “Places API (New)” → Save. This makes the key useless if it ever leaks."),
      numbered("Paste it into Secrets as ", [code("GOOGLE_MAPS_API_KEY"), t(".")]),
      H2("Cost — effectively free for you"),
      bullet([t("Pay-as-you-go with a monthly free allowance. For this app (a few hundred lookups, and each is cached so it's only fetched once) you'll almost certainly pay "), bold("$0"), t(".")]),
      bullet([t("A card is required to activate, that's the main catch. To stay 100% safe, set a tiny budget alert: Billing → “Budgets & alerts” → create a $5 budget so Google emails you if anything is ever charged.")]),
      bullet([t("Google revised Maps pricing in 2025 — the exact free thresholds are shown in your console; the takeaway (near-zero for your volume) stands.")]),
      P(" "),

      // ─────────────────────────────────────────────────────────────
      H1("4. OpenCorporates API token"),
      P([bold("What it does in the app: "), t("checks company registries and flags any newly-registered Arizona/Delaware subsidiary — a strong “they're moving to the US” signal.")]),
      numbered("Go to ", [link("opencorporates.com/api_accounts/new", "https://opencorporates.com/api_accounts/new"), t(" (or the “API” link in their website footer).")]),
      numbered("Apply for an API account and describe your use case."),
      numbered("Once approved, copy your token into Secrets as ", [code("OPENCORPORATES_API_TOKEN"), t(".")]),
      callout([ P([bold("Reality check on “free.” "), t("OpenCorporates restricts free API access to non-commercial and public-benefit projects. A commercial B2B intelligence product likely does "), bold("not"), t(" qualify for the free tier, so you may be pointed to a paid plan (pricing on request, not published). Verify this when you apply — don't assume it'll be free for this use.")], { spacing: { after: 0 } }) ]),
      P(" "),

      // ─────────────────────────────────────────────────────────────
      H1("5. ImportYeti / Bill-of-Lading data"),
      P([bold("What it does in the app: "), t("finds suppliers already shipping ocean freight to Arizona — the hardest evidence that a move is underway.")]),
      H2("The honest situation"),
      bullet([bold("ImportYeti itself has no official public API. "), t("So there's no “ImportYeti key” to paste in the normal sense.")]),
      bullet([t("The "), link("importyeti.com", "https://www.importyeti.com"), t(" website is "), bold("free to search by hand"), t(" — type a supplier, see its US customers and shipment counts. Perfect for spot checks at $0.")]),
      bullet([t("To "), bold("automate"), t(" this inside the dashboard, you subscribe to a Bill-of-Lading data provider that does offer an API, then paste its endpoint + key into "), code("IMPORTYETI_API_BASE"), t(" and "), code("IMPORTYETI_API_KEY"), t(".")]),
      H2("Cost — ongoing, not one-time (if you automate)"),
      P([t("Rough monthly pricing for providers that have APIs (")," ", bold("verify — these change"), t("):")]),
      bullet([bold("ImportGenius"), t(" — roughly $100–$400+/month; API on higher tiers.")]),
      bullet([bold("Panjiva (S&P Global)"), t(" — enterprise, custom pricing (typically thousands per year).")]),
      bullet([bold("Trademo"), t(" — custom pricing.")]),
      callout([ P([bold("My recommendation: "), t("start free and manual. Use the ImportYeti website yourself for the handful of suppliers you care about, and only pay for a Bill-of-Lading API if you later need it automated across hundreds of companies. There is "), bold("no one-time option"), t(" for a live data feed — an API is an ongoing monthly subscription.")], { spacing: { after: 0 } }) ]),
      P(" "),

      // ─────────────────────────────────────────────────────────────
      H1("6. Cost summary"),
      costTable(),
      P(" "),
      P([t("Bottom line: "), bold("Google Places ≈ free"), t(" for you, "), bold("OpenCorporates may cost money"), t(" for commercial use, and "), bold("ImportYeti is $0 manual or an ongoing subscription if automated"), t(". None of them are required for the app to run.")]),
      P(" "),

      // ─────────────────────────────────────────────────────────────
      H1("7. Paste-ready Secrets block"),
      P([t("Copy this into the Secrets box (Section 1), fill in the quotes, and delete any line you're not using yet:")]),
      codeBlock([
        '# ── OSINT API keys (leave blank to keep mock data) ──',
        'GOOGLE_MAPS_API_KEY = ""',
        'OPENCORPORATES_API_TOKEN = ""',
        'IMPORTYETI_API_BASE = ""',
        'IMPORTYETI_API_KEY = ""',
        '',
        '# ── Login (delete this whole section to keep the app open) ──',
        '[passwords]',
        'admin = "change-me-to-a-strong-password"',
      ]),
      P(" "),
      P([new TextRun({ text: "Prices and free-tier rules quoted here are approximate and change often — confirm the current numbers on each provider's site before committing. Generated for Project Sauron.", italics: true, color: GREY, size: 18 })]),
    ],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[2] || "SETUP_GUIDE.docx", buf);
  console.log("wrote", process.argv[2] || "SETUP_GUIDE.docx");
});
