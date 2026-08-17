import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BarChart3,
  CheckCircle2,
  ChevronRight,
  FileUp,
  ExternalLink,
  FileJson,
  Mail,
  LockKeyhole,
  LogOut,
  Menu,
  MessageCircle,
  Phone,
  Pencil,
  Plus,
  Rocket,
  Search,
  Send,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { api } from "./api";
import "./styles.css";
import "./advanced.css";
import "./sheets.css";
import "./auth.css";
import "./prospects.css";
import "./composer.css";
import "./mobile.css";
const MSG = `Bonjour {first_name},\n\nJ'ai identifié une piste concrète pour aider {business_name} à automatiser son acquisition et sa qualification commerciale.\n\nJe peux vous montrer le fonctionnement en 15 minutes : {calendar_url}`;
const CHANNEL_MESSAGES = {
  email: MSG,
  whatsapp: "Bonjour {first_name}, j'ai une idée concrète pour {business_name}. Puis-je vous l'expliquer rapidement ici ou lors d'un échange ? {calendar_url}",
  sms: "Bonjour {first_name}, une idée pour aider {business_name}. Échangeons 15 min : {calendar_url}",
};
const blank = {
  name: "Nouvelle campagne",
  sector: "",
  objective: "book_meeting",
  tags: "",
  channel: "email",
  provider: "emelia",
  subject: "Une piste pour {business_name}",
  message: MSG,
  calendar_url: "",
  video_url: "",
  content_type: "text",
  scheduled_at: "",
  time_zone: "Europe/Paris",
};
const nav = [
  ["cockpit", BarChart3, "Cockpit"],
  ["campaigns", Rocket, "Campagnes"],
  ["prospects", Search, "Prospects"],
  ["conversations", MessageCircle, "Conversations"],
  ["compliance", ShieldCheck, "Conformité"],
];
const pagePaths = {
  cockpit: "/",
  campaigns: "/campagnes",
  prospects: "/prospects",
  conversations: "/conversations",
  compliance: "/conformite",
};
const pathPages = Object.fromEntries(Object.entries(pagePaths).map(([page, path]) => [path, page]));
const pageFromLocation = () => pathPages[window.location.pathname.replace(/\/$/, "") || "/"] || "cockpit";
function Root() {
  const [authenticated, setAuthenticated] = useState(
    Boolean(localStorage.getItem("ambs_token")),
  );
  useEffect(() => {
    const handler = () => setAuthenticated(false);
    window.addEventListener("ambs:logout", handler);
    return () => window.removeEventListener("ambs:logout", handler);
  }, []);
  const logout = () => {
    localStorage.removeItem("ambs_token");
    setAuthenticated(false);
  };
  return authenticated ? (
    <App logout={logout} />
  ) : (
    <Login
      success={(token) => {
        localStorage.setItem("ambs_token", token);
        setAuthenticated(true);
      }}
    />
  );
}
function Login({ success }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      success((await api.login(email, password)).access_token);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <span className="login-logo">
          <Rocket />
        </span>
        <p className="eyebrow">AMBS OUTREACH ENGINE</p>
        <h1>Connexion</h1>
        <p>Accédez à votre cockpit de prospection.</p>
        {error && <div className="login-error">{error}</div>}
        <label>
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Mot de passe
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button className="primary" disabled={busy}>
          <LockKeyhole />
          {busy ? "Connexion…" : "Se connecter"}
        </button>
      </form>
    </main>
  );
}
function App({ logout }) {
  const [page, setPage] = useState(pageFromLocation),
    [campaigns, setCampaigns] = useState([]),
    [analytics, setAnalytics] = useState({}),
    [config, setConfig] = useState({}),
    [selected, setSelected] = useState(null),
    [contacts, setContacts] = useState([]),
    [steps, setSteps] = useState([]),
    [prospects, setProspects] = useState([]),
    [jobs, setJobs] = useState([]),
    [conversations, setConversations] = useState([]),
    [deliveries, setDeliveries] = useState([]),
    [suppressions, setSuppressions] = useState([]),
    [modal, setModal] = useState(false),
    [form, setForm] = useState(blank),
    [preview, setPreview] = useState(null),
    [notice, setNotice] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const guard = async (fn) => {
    setError("");
    try {
      return await fn();
    } catch (e) {
      setError(e.message);
      throw e;
    }
  };
  const refresh = () =>
    guard(async () => {
      const [c, a, cfg] = await Promise.all([
        api.campaigns(),
        api.analytics(),
        api.config(),
      ]);
      setCampaigns(c);
      setAnalytics(a);
      setConfig(cfg);
    }).catch(() => {});
  useEffect(() => {
    let active = true;
    Promise.all([api.campaigns(), api.analytics(), api.config()])
      .then(([c, a, cfg]) => {
        if (active) {
          setCampaigns(c);
          setAnalytics(a);
          setConfig(cfg);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    const onPopState = () => go(pageFromLocation(), false);
    window.addEventListener("popstate", onPopState);
    if (page !== "cockpit") go(page, false);
    return () => window.removeEventListener("popstate", onPopState);
    // Navigation data is loaded once on mount and on browser back/forward.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function go(next, updateHistory = true) {
    const target = pagePaths[next] ? next : "cockpit";
    if (updateHistory && window.location.pathname !== pagePaths[target]) {
      window.history.pushState({ page: target }, "", pagePaths[target]);
    }
    setPage(target);
    setMobileMenuOpen(false);
    setError("");
    try {
      if (target === "prospects") {
        const [rows, runs] = await Promise.all([
          api.prospects(),
          api.prospectingJobs(),
        ]);
        setProspects(rows);
        setJobs(runs);
      }
      if (target === "conversations") {
        const [c, d] = await Promise.all([
          api.conversations(),
          api.deliveries(),
        ]);
        setConversations(c);
        setDeliveries(d);
      }
      if (target === "compliance") setSuppressions(await api.suppressions());
    } catch (e) {
      setError(e.message);
    }
  }
  async function toggleMode() {
    const enableLive = config.dry_run !== false;
    if (enableLive && !window.confirm("Activer les envois réels ? Les prochaines campagnes pourront contacter de vraies personnes via les fournisseurs configurés.")) return;
    setBusy(true);
    try {
      const updated = await guard(() => api.setMode(!enableLive, enableLive));
      setConfig((current) => ({ ...current, dry_run: updated.dry_run }));
      setNotice(updated.dry_run ? "Mode simulation activé." : "Mode réel activé. Vérifiez la campagne avant chaque envoi.");
    } finally {
      setBusy(false);
    }
  }
  async function open(c) {
    setSelected(c);
    setPreview(null);
    const [p, s] = await Promise.all([api.contacts(c.id), api.sequence(c.id)]);
    setContacts(p);
    setSteps(s);
  }
  async function create(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const payload = { ...form, scheduled_at: form.scheduled_at ? new Date(form.scheduled_at).toISOString() : null };
      let c = await guard(() => api.create(payload));
      if (form.scheduled_at) c = await guard(() => api.scheduleCampaign(c.id, payload.scheduled_at, config.dry_run === false));
      setModal(false);
      setForm(blank);
      await refresh();
      await open(c);
      await go("campaigns");
      setNotice(form.scheduled_at ? "Campagne créée et programmée." : "Campagne créée en brouillon.");
    } finally {
      setBusy(false);
    }
  }
  async function upload(e) {
    const f = e.target.files[0];
    if (!f) return;
    setBusy(true);
    try {
      const r = await guard(() => api.upload(selected.id, f));
      setNotice(
        `${r.added} ajoutés, ${r.duplicates} doublons, ${r.invalid} invalides.`,
      );
      await open(selected);
      await refresh();
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }
  async function addStep() {
    const channel = prompt("Canal : email, sms ou whatsapp", "email");
    if (!["email", "sms", "whatsapp"].includes(channel)) return;
    const delay = Number(prompt("Délai en heures", "48"));
    const message = prompt(
      "Message de relance",
      "Bonjour {first_name}, avez-vous vu ma proposition ? {calendar_url}",
    );
    if (!message) return;
    await guard(() =>
      api.addStep(selected.id, {
        channel,
        provider:
          channel === "email"
            ? "emelia"
            : channel === "sms"
              ? "isendpro"
              : "ambs",
        delay_hours: delay,
        message,
        subject: channel === "email" ? "Suite à mon message" : "",
      }),
    );
    await open(selected);
  }
  async function launch() {
    const remaining = contacts.filter((contact) => contact.status === "ready" && !contact.opted_out).length;
    if (!remaining) {
      setNotice("Aucun contact restant à traiter dans cette campagne.");
      return;
    }
    if (
      !confirm(
        `${config.dry_run ? "Simuler" : "Envoyer"} progressivement la campagne pour ${remaining} contact${remaining > 1 ? "s" : ""} ?`,
      )
    )
      return;
    setBusy(true);
    try {
      const r = await guard(() => api.send(selected.id, Math.min(remaining, 500), config.dry_run === false));
      let providerError = "";
      if (r.failed) {
        const recent = await api.deliveries();
        providerError = recent.find((item) => item.campaign === selected.name && item.status === "failed")?.error || "";
      }
      setNotice(`${r.processed} traités, ${r.queued} envoyés immédiatement, ${r.simulated} simulés, ${r.failed} erreurs${providerError ? ` · ${providerError}` : ""}${r.remaining ? `, ${r.remaining} restants` : ""}.`);
      await open(selected);
      await refresh();
    } finally {
      setBusy(false);
    }
  }
  async function pauseSelectedCampaign() {
    if (!selected || !window.confirm(`Mettre en pause « ${selected.name} » dans Emelia ?`)) return;
    setBusy(true);
    try {
      const updated = await guard(() => api.pauseCampaign(selected.id));
      setSelected(updated);
      setNotice("Campagne mise en pause dans AMBS et Emelia.");
      await refresh();
    } finally {
      setBusy(false);
    }
  }
  async function resumeSelectedCampaign() {
    if (!selected || !window.confirm(`Reprendre « ${selected.name} » dans Emelia ?`)) return;
    setBusy(true);
    try {
      const updated = await guard(() => api.resumeCampaign(selected.id));
      setSelected(updated);
      setNotice("Campagne reprise dans AMBS et Emelia.");
      await refresh();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="shell">
      {mobileMenuOpen && <button className="sidebar-backdrop" aria-label="Fermer le menu" onClick={() => setMobileMenuOpen(false)} />}
      <aside className={mobileMenuOpen ? "mobile-open" : ""}>
        <div className="brand">
          <span className="mark">
            <Rocket />
          </span>
          <div>
            <strong>AMBS</strong>
            <small>OUTREACH ENGINE</small>
          </div>
          <button className="sidebar-close" aria-label="Fermer le menu" onClick={() => setMobileMenuOpen(false)}><X /></button>
        </div>
        <nav>
          {nav.map(([id, Icon, label]) => (
            <button
              key={id}
              className={page === id ? "active" : ""}
              onClick={() => go(id)}
            >
              <Icon />
              {label}
            </button>
          ))}
        </nav>
        <div className="aside-foot mode-control">
          <div>
            <span className={`dot ${config.dry_run ? "amber" : ""}`} />
            <span>{config.dry_run ? "Mode simulation" : "Mode réel"}</span>
          </div>
          <label className="mode-switch" title="Basculer entre simulation et envoi réel">
            <input type="checkbox" checked={config.dry_run === false} disabled={busy} onChange={toggleMode} />
            <span />
          </label>
        </div>
        <button className="logout" onClick={logout}>
          <LogOut />
          Déconnexion
        </button>
      </aside>
      <main className={page === "prospects" ? "prospects-main" : ""}>
        <header>
          <button className="mobile-menu-button" aria-label="Ouvrir le menu" onClick={() => setMobileMenuOpen(true)}><Menu /></button>
          <div className="header-copy">
            <p className="eyebrow">AMBS / {page.toUpperCase()}</p>
            <h1>{nav.find((n) => n[0] === page)?.[2]}</h1>
            <p>Orchestration commerciale multicanale, tous secteurs.</p>
          </div>
          <button className="primary" onClick={() => setModal(true)}>
            <Plus />
            Nouvelle campagne
          </button>
        </header>
        {error && <Alert error text={error} close={() => setError("")} />}{" "}
        {notice && <Alert text={notice} close={() => setNotice("")} />}
        {page !== "prospects" && <Stats a={analytics} />}
        {page === "cockpit" && (
          <Cockpit campaigns={campaigns} deliveries={deliveries} go={go} />
        )}{" "}
        {page === "campaigns" && (
          <Campaigns
            key={selected?.channel || "email"}
            campaigns={campaigns}
            selected={selected}
            contacts={contacts}
            steps={steps}
            open={open}
            upload={upload}
            addStep={addStep}
            preview={preview}
            showPreview={() =>
              guard(async () =>
                setPreview(await api.preview(selected.id)),
              ).catch(() => {})
            }
            launch={launch}
            pauseCampaign={pauseSelectedCampaign}
            resumeCampaign={resumeSelectedCampaign}
            dryRun={config.dry_run}
            busy={busy}
          />
        )}{" "}
        {page === "prospects" && (
          <Prospects
            rows={prospects}
            jobs={jobs}
            campaigns={campaigns}
            refresh={async () => {
              const [rows, runs] = await Promise.all([
                api.prospects(),
                api.prospectingJobs(),
              ]);
              setProspects(rows);
              setJobs(runs);
            }}
            notify={setNotice}
          />
        )}{" "}
        {page === "conversations" && (
          <Conversations rows={conversations} deliveries={deliveries} />
        )}{" "}
        {page === "compliance" && (
          <Compliance
            rows={suppressions}
            add={async (value) => {
              await api.suppress(value);
              setSuppressions(await api.suppressions());
            }}
          />
        )}
      </main>
      {modal && (
        <CampaignModal
          form={form}
          setForm={setForm}
          close={() => setModal(false)}
          submit={create}
          busy={busy}
          error={error}
        />
      )}
    </div>
  );
}
function Alert({ text, error, close }) {
  return (
    <div className={`notice ${error ? "error-box" : ""}`}>
      {error ? <ShieldCheck /> : <CheckCircle2 />}
      {text}
      <button onClick={close}>
        <X />
      </button>
    </div>
  );
}
function Stats({ a }) {
  return (
    <section className="stats">
      <Stat icon={<Rocket />} label="Campagnes" value={a.campaigns || 0} />
      <Stat icon={<Users />} label="Contacts" value={a.contacts || 0} />
      <Stat icon={<Send />} label="Livraisons" value={a.deliveries || 0} />
      <Stat
        icon={<ShieldCheck />}
        label="Oppositions"
        value={a.opted_out || 0}
      />
    </section>
  );
}
function Stat(p) {
  return (
    <article>
      {p.icon}
      <div>
        <strong>{p.value}</strong>
        <span>{p.label}</span>
      </div>
    </article>
  );
}
function Cockpit({ campaigns, go }) {
  return (
    <section className="dashboard-grid">
      <article className="panel">
        <h2>Activité récente</h2>
        {campaigns.slice(0, 6).map((c) => (
          <div className="activity" key={c.id}>
            <Channel type={c.channel} />
            <div>
              <strong>{c.name}</strong>
              <small>
                {c.sector || "Tous secteurs"} · {c.contact_count} contacts
              </small>
            </div>
            <span>{c.status}</span>
          </div>
        ))}
        {!campaigns.length && <Empty text="Aucune campagne pour le moment." />}
      </article>
      <article className="panel">
        <h2>État des connecteurs</h2>
        <p>Configurez Emelia, iSendPro et AMBS dans le fichier backend/.env.</p>
        <button onClick={() => go("campaigns")}>
          Configurer une campagne <ChevronRight />
        </button>
      </article>
    </section>
  );
}
function Campaigns({
  campaigns,
  selected,
  contacts,
  steps,
  open,
  upload,
  addStep,
  preview,
  showPreview,
  launch,
  pauseCampaign,
  resumeCampaign,
  dryRun,
  busy,
}) {
  const [channelFilter, setChannelFilter] = useState(selected?.channel || "email");
  const visibleCampaigns = campaigns.filter(
    (campaign) => campaign.channel === channelFilter,
  );
  const readyCount = contacts.filter((contact) => contact.status === "ready" && !contact.opted_out).length;
  return (
    <section className="workspace">
      <div className="campaign-list">
        <div className="channel-tabs">
          {["email", "whatsapp", "sms"].map((channel) => (
            <button
              key={channel}
              className={channelFilter === channel ? "active" : ""}
              onClick={() => setChannelFilter(channel)}
            >
              {channel}
            </button>
          ))}
        </div>
        <div className="section-title">
          <h2>Campagnes</h2>
          <span>{visibleCampaigns.length}</span>
        </div>
        {visibleCampaigns.map((c) => (
          <button
            className={`campaign ${selected?.id === c.id ? "selected" : ""}`}
            onClick={() => open(c)}
            key={c.id}
          >
            <Channel type={c.channel} />
            <div>
              <strong>{c.name}</strong>
              <small>
                {c.sector || "Tous secteurs"} · {c.contact_count}
              </small>
            </div>
            <ChevronRight />
          </button>
        ))}
      </div>
      <div className="detail">
        {!selected ? (
          <Empty text="Sélectionnez une campagne." />
        ) : (
          <>
            <div className="detail-head">
              <div>
                <span className="pill">{selected.channel}</span>
                <h2>{selected.name}</h2>
                <p>
                  {selected.objective} · {selected.tags || "sans tags"}
                </p>
                {selected.channel === "email" && selected.external_id && (
                  <p className="sync-state">Emelia · {selected.sender_email} · {selected.external_status || "DRAFT"}</p>
                )}
              </div>
              <label className="upload">
                <FileUp />
                Importer CSV
                <input type="file" accept=".csv" onChange={upload} />
              </label>
            </div>
            <div className="campaign-flow">
              <div className="flow-card done"><b>1</b><div><strong>Canal</strong><span>{selected.channel.toUpperCase()} · messages issus des prospects</span></div></div>
              <div className={`flow-card ${contacts.length ? "done" : ""}`}><b>2</b><div><strong>Destinataires</strong><span>{contacts.length} contact{contacts.length > 1 ? "s" : ""}</span></div></div>
              <div className={`flow-card ${selected.scheduled_at ? "done" : ""}`}><b>3</b><div><strong>Envoi</strong><span>{selected.scheduled_at ? `Programmé · ${new Date(selected.scheduled_at).toLocaleString("fr-FR")}` : "Immédiat au clic sur Envoyer"}</span></div></div>
              <div className={`flow-card ${["running", "completed", "simulated"].includes(selected.status) ? "done" : ""}`}><b>4</b><div><strong>Résultats</strong><span>{selected.status}</span></div></div>
            </div>
            <div className="sequence advanced-sequence">
              <div className="sequence-title">
                <strong>Relances automatiques</strong>
                <button onClick={addStep}>
                  <Plus />
                  Ajouter une étape
                </button>
              </div>
              {steps.map((s) => (
                <Step
                  key={s.id}
                  n={s.position + 1}
                  channel={s.channel}
                  text={`Relance ${s.channel}`}
                  sub={`Après ${s.delay_hours} h · ${s.provider}`}
                />
              ))}
              {!steps.length && <small>Aucune relance configurée. Le premier message vient de chaque fiche prospect.</small>}
            </div>
            <div className="actions">
              <button onClick={showPreview}>Prévisualiser</button>
              {selected.channel === "email" && selected.external_status === "RUNNING" && (
                <button disabled={busy} onClick={pauseCampaign}>Mettre en pause</button>
              )}
              {selected.channel === "email" && selected.external_status === "PAUSED" && (
                <button disabled={busy} onClick={resumeCampaign}>Reprendre</button>
              )}
              <button
                className="primary"
                disabled={busy || !readyCount}
                onClick={launch}
              >
                <Send />
                {dryRun ? "Simuler" : "Envoyer"} {readyCount || 0} contact{readyCount > 1 ? "s" : ""}
              </button>
            </div>
            {preview && selected.content_type !== "html" && (
              <div className="preview">
                <strong>{preview.subject}</strong>
                <p>{preview.message}</p>
              </div>
            )}
            {preview && selected.content_type === "html" && (
              <div className="preview">
                <strong>{preview.subject}</strong>
                <iframe
                  title="Aperçu HTML"
                  sandbox=""
                  className="html-preview"
                  srcDoc={preview.message}
                />
              </div>
            )}
            <ContactTable rows={contacts} />
          </>
        )}
      </div>
    </section>
  );
}
function Audiences({ rows, campaigns, search, imported }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState([]);
  const [source, setSource] = useState("");
  const [meta, setMeta] = useState(null);
  const [tab, setTab] = useState("");
  const [data, setData] = useState(null);
  const [campaign, setCampaign] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function connect() {
    setOpen(true);
    setLoading(true);
    setError("");
    try {
      setFiles((await api.sheets()).files);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  async function choose(value) {
    setSource(value);
    setData(null);
    if (!value) return;
    setLoading(true);
    try {
      const metadata = await api.sheetMetadata(value);
      setMeta(metadata);
      const first = metadata.sheets[0]?.title || "";
      setTab(first);
      if (first) setData(await api.sheetPreview(value, first));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  async function chooseTab(value) {
    setTab(value);
    setLoading(true);
    try {
      setData(await api.sheetPreview(source, value));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  async function doImport() {
    setLoading(true);
    try {
      const result = await api.importSheet(Number(campaign), source, tab);
      await imported(
        `${result.added} contacts importés depuis ${result.source} / ${result.sheet_name}.`,
      );
      setOpen(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  return (
    <>
      <section className="panel">
        <div className="toolbar">
          <h2>Audience globale</h2>
          <div className="toolbar-actions">
            <button type="button" onClick={connect}>
              <FileUp />
              Google Sheets
            </button>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                search(q);
              }}
            >
              <Search />
              <input
                placeholder="Nom, société ou email"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <button>Rechercher</button>
            </form>
          </div>
        </div>
        <ContactTable rows={rows} />
      </section>
      {open && (
        <div className="overlay">
          <div className="modal sheet-modal">
            <div className="modal-head">
              <div>
                <p className="eyebrow">SOURCE DE DONNÉES</p>
                <h2>Google Sheets</h2>
              </div>
              <button onClick={() => setOpen(false)}>
                <X />
              </button>
            </div>
            {error && <Alert error text={error} close={() => setError("")} />}
            <div className="sheet-controls">
              <label>
                Classeur
                <select value={source} onChange={(e) => choose(e.target.value)}>
                  <option value="">Choisir un fichier</option>
                  {files.map((file) => (
                    <option key={file.id} value={file.id}>
                      {file.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Onglet
                <select
                  value={tab}
                  disabled={!meta}
                  onChange={(e) => chooseTab(e.target.value)}
                >
                  {meta?.sheets.map((sheet) => (
                    <option key={sheet.sheet_id}>{sheet.title}</option>
                  ))}
                </select>
              </label>
              <label>
                Campagne de destination
                <select
                  value={campaign}
                  onChange={(e) => setCampaign(e.target.value)}
                >
                  <option value="">Choisir une campagne</option>
                  {campaigns.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {loading && (
              <div className="loading">Lecture de Google Sheets…</div>
            )}
            {data && (
              <>
                <p className="sheet-summary">
                  <strong>{data.spreadsheet_name}</strong> · {data.sheet_name} ·{" "}
                  {data.total_rows} lignes
                </p>
                <div className="sheet-preview">
                  <table>
                    <thead>
                      <tr>
                        {data.headers.slice(0, 12).map((header) => (
                          <th key={header}>{header}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.rows.slice(0, 20).map((row, index) => (
                        <tr key={index}>
                          {data.headers.slice(0, 12).map((header) => (
                            <td key={header}>{row[header]}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            <div className="modal-actions">
              <button onClick={() => setOpen(false)}>Fermer</button>
              <button
                className="primary"
                disabled={!campaign || !data || loading}
                onClick={doImport}
              >
                Importer dans AMBS
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
function Prospects({ rows, jobs, campaigns, refresh, notify }) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState(""),
    [location, setLocation] = useState(""),
    [limit, setLimit] = useState(50),
    [busy, setBusy] = useState(false),
    [selected, setSelected] = useState([]),
    [campaign, setCampaign] = useState(""),
    [search, setSearch] = useState(""),
    [statusFilter, setStatusFilter] = useState(""),
    [detail, setDetail] = useState(null),
    [messageEditor, setMessageEditor] = useState(null);
  const wasCollecting = useRef(false);
  const collectionRunning = jobs.some((job) => ["queued", "running"].includes(job.status));
  useEffect(() => {
    if (!collectionRunning) {
      if (wasCollecting.current) {
        wasCollecting.current = false;
        notify("Prospection terminée : la liste des prospects a été actualisée automatiquement.");
      }
      return undefined;
    }
    wasCollecting.current = true;
    const timer = window.setInterval(() => refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [collectionRunning, refresh, notify]);
  const statusLabels = {
    new: "Nouveau",
    targeted: "Dans une campagne",
    contacted: "Déjà contacté",
    failed: "Échec d'envoi",
    opted_out: "Désinscrit",
  };
  const visibleRows = rows.filter((row) => {
    const term = search.trim().toLowerCase();
    const matchesSearch = !term || [row.business_name, row.email, row.phone, row.city, row.category]
      .some((value) => String(value || "").toLowerCase().includes(term));
    return matchesSearch && (!statusFilter || row.crm_status === statusFilter);
  });
  async function launch(event) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.startProspecting({ query, location, limit: Number(limit) });
      setOpen(false);
      notify(
        "Prospection lancée. Les résultats arriveront directement dans PostgreSQL.",
      );
      await refresh();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function assign() {
    if (!campaign) return;
    setBusy(true);
    try {
      const result = await api.addProspectsToCampaign(
        Number(campaign),
        selected,
      );
      notify(
        `${result.added} prospects ajoutés à la campagne, ${result.invalid} sans destination exploitable.`,
      );
      setSelected([]);
      await refresh();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function importFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    setBusy(true);
    try {
      const result = await api.importProspects(file);
      notify(`${result.added} prospects importés, ${result.emails} emails et ${result.updated} mises à jour.`);
      await refresh();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }
  const toggle = (id) =>
    setSelected((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id],
    );
  return (
    <>
      <section className="prospects-page">
        <div className="toolbar">
          <div>
            <h2>Base de prospects</h2>
            <p>{rows.length} prospects premium · email et téléphone vérifiés</p>
            {collectionRunning && <span className="live-refresh"><i /> Collecte en cours · actualisation automatique</span>}
          </div>
          <div className="toolbar-actions">
            <input
              className="prospect-search"
              placeholder="Entreprise, email, téléphone…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">Tous les statuts</option>
              {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <label className="upload"><FileUp />Importer Excel / CSV<input type="file" accept=".csv,.xlsx,.xlsm" onChange={importFile} /></label>
            <button onClick={refresh}>Actualiser</button>
            <button className="primary" onClick={() => setOpen(true)}>
              <Plus />
              Lancer une prospection
            </button>
          </div>
        </div>
        {collectionRunning && jobs.length > 0 && (
          <div className="job-strip">
            {jobs.slice(0, 5).map((job) => (
              <div key={job.id} className={`job ${job.status}`}>
                <strong>{job.query}</strong>
                <span>{job.location}</span>
                <b>
                  {job.status} · {job.found_count}/{job.requested_limit}
                </b>
              </div>
            ))}
          </div>
        )}
        <div className="prospect-actions">
          <span>{selected.length} sélectionnés</span>
          <select
            value={campaign}
            onChange={(e) => setCampaign(e.target.value)}
          >
            <option value="">Campagne de destination</option>
            {campaigns.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.channel})
              </option>
            ))}
          </select>
          <button disabled={!campaign || busy} onClick={assign}>
            Ajouter à la campagne
          </button>
        </div>
        <div className="table-wrap prospects-table-scroll">
          <table className="prospects-table">
            <thead>
              <tr>
                <th></th>
                <th>Prospect</th>
                <th>Coordonnées</th>
                <th>Qualité</th>
                <th>Site</th>
                <th>Email pré-écrit</th>
                <th>WhatsApp pré-écrit</th>
                <th>SMS pré-écrit</th>
                <th>Statut</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((p) => (
                <tr key={p.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.includes(p.id)}
                      onChange={() => toggle(p.id)}
                    />
                  </td>
                  <td>
                    <strong>{p.business_name}</strong>
                    <small>{p.category} · {p.city || p.country}</small>
                    <small>{p.decision_maker_name || "Décideur non identifié"} · {p.decision_maker_role || "fonction inconnue"}</small>
                  </td>
                  <td><a className="contact-link" href={`mailto:${p.email}`}>{p.email}</a><a className="contact-link" href={`tel:${p.phone}`}>{p.phone}</a></td>
                  <td><span className={`quality-badge ${p.validation_status}`}>{p.quality_score}/100</span><small>{p.validation_status}</small></td>
                  <td>{p.website ? <a className="website-button" href={p.website} target="_blank" rel="noreferrer"><ExternalLink /> Visiter</a> : "—"}</td>
                  <td className="message-cell"><strong>{p.email_subject || "Sans objet"}</strong><span title={p.email_message}>{p.email_message || "—"}</span></td>
                  <td className="message-cell"><span title={p.whatsapp_message}>{p.whatsapp_message || "—"}</span></td>
                  <td className="message-cell"><span title={p.sms_message}>{p.sms_message || "—"}</span><small>{(p.sms_message || "").length}/160</small></td>
                  <td><span className={`status ${p.crm_status}`}>{statusLabels[p.crm_status] || p.crm_status}</span><small>{p.campaign_count ? `${p.campaign_count} campagne(s)` : "Aucune campagne"}</small></td>
                  <td className="row-buttons"><button className="edit-message-button" onClick={() => setMessageEditor(p)}><Pencil /> Messages</button><button className="metadata-button" title="Voir les données originales" onClick={() => setDetail(p)}><FileJson /> Métadonnées</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!visibleRows.length && (
            <Empty text="Aucun prospect. Lancez votre première recherche." />
          )}
        </div>
      </section>
      {detail && <ProspectMetadata prospect={detail} close={() => setDetail(null)} />}
      {messageEditor && <ProspectMessageEditor prospect={messageEditor} close={() => setMessageEditor(null)} saved={async () => { setMessageEditor(null); await refresh(); notify("Messages du prospect enregistrés."); }} />}
      {open && (
        <div className="overlay">
          <form className="modal prospect-modal" onSubmit={launch}>
            <div className="modal-head">
              <div>
                <p className="eyebrow">NOUVELLE COLLECTE</p>
                <h2>Lancer une prospection</h2>
              </div>
              <button type="button" onClick={() => setOpen(false)}>
                <X />
              </button>
            </div>
            <label>
              Type d'entreprise / recherche
              <input
                required
                placeholder="agences immobilières, hôtels, cabinets comptables…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <label>
              Zone géographique
              <input
                required
                placeholder="Lyon, Nantes, Île-de-France…"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
            </label>
            <label>
              Nombre maximum
              <input
                type="number"
                min="1"
                max="500"
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
              />
            </label>
            <div className="modal-actions">
              <button type="button" onClick={() => setOpen(false)}>
                Annuler
              </button>
              <button className="primary" disabled={busy}>
                {busy ? "Lancement…" : "Lancer la collecte"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
function ProspectMetadata({ prospect, close }) {
  return <div className="overlay"><div className="modal prospect-detail-modal">
    <div className="modal-head"><div><p className="eyebrow">MÉTADONNÉES DU PROSPECT</p><h2>{prospect.business_name}</h2></div><button onClick={close}><X /></button></div>
    <div className="metadata-summary"><div><small>Source</small><strong>{prospect.email_source || "—"}</strong></div><div><small>Validation</small><strong>{prospect.validation_notes || "—"}</strong></div><div><small>Google Maps</small>{prospect.google_maps_url ? <a href={prospect.google_maps_url} target="_blank" rel="noreferrer">Ouvrir la fiche</a> : <strong>—</strong>}</div></div>
    <div className="raw-data-grid">{Object.entries(prospect.raw_data || {}).map(([key,value]) => <div key={key}><small>{key}</small><span>{String(value)}</span></div>)}</div>
    <div className="modal-actions"><button className="primary" onClick={close}>Fermer</button></div>
  </div></div>;
}
function ProspectMessageEditor({ prospect, close, saved }) {
  const [form, setForm] = useState({
    email_subject: prospect.email_subject || "",
    email_message: prospect.email_message || "",
    whatsapp_message: prospect.whatsapp_message || "",
    sms_message: prospect.sms_message || "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const field = (name, value) => setForm((current) => ({ ...current, [name]: value }));
  async function submit(event) {
    event.preventDefault(); setSaving(true); setError("");
    try { await api.updateProspectMessages(prospect.id, form); await saved(); }
    catch (e) { setError(e.message); }
    finally { setSaving(false); }
  }
  return <div className="drawer-overlay" onMouseDown={close}><form className="message-drawer" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
    <div className="drawer-head"><div><p className="eyebrow">MESSAGES PERSONNALISÉS</p><h2>{prospect.business_name}</h2><span>{prospect.email} · {prospect.phone}</span></div><button type="button" onClick={close}><X /></button></div>
    {error && <div className="login-error">{error}</div>}
    <div className="editor-channel email"><div><Mail /><strong>Email</strong></div><label>Objet<input value={form.email_subject} onChange={(e) => field("email_subject", e.target.value)} /></label><label>Message<textarea rows="9" value={form.email_message} onChange={(e) => field("email_message", e.target.value)} /></label></div>
    <div className="editor-channel whatsapp"><div><MessageCircle /><strong>WhatsApp</strong></div><label>Message<textarea rows="6" value={form.whatsapp_message} onChange={(e) => field("whatsapp_message", e.target.value)} /></label></div>
    <div className="editor-channel sms"><div><Phone /><strong>SMS</strong><span className={form.sms_message.length > 160 ? "over" : ""}>{form.sms_message.length}/160</span></div><label>Message<textarea rows="4" maxLength="160" value={form.sms_message} onChange={(e) => field("sms_message", e.target.value)} /></label></div>
    <div className="drawer-actions"><button type="button" onClick={close}>Annuler</button><button className="primary" disabled={saving || form.sms_message.length > 160}>{saving ? "Enregistrement…" : "Enregistrer les messages"}</button></div>
  </form></div>;
}
function Conversations({ rows, deliveries }) {
  return (
    <section className="dashboard-grid">
      <article className="panel">
        <h2>Conversations</h2>
        {rows.length ? (
          rows.map((r) => (
            <div className="activity" key={r.id}>
              <Channel type={r.channel} />
              <div>
                <strong>{r.contact || r.business_name}</strong>
                <small>{r.last_message || "Aucun message entrant"}</small>
              </div>
              <span>{r.paused ? "humain" : "IA"}</span>
            </div>
          ))
        ) : (
          <Empty text="Aucune conversation reçue." />
        )}
      </article>
      <article className="panel">
        <h2>Journal des livraisons</h2>
        {deliveries.slice(0, 30).map((d) => (
          <div className="activity" key={d.id}>
            <Channel type={d.channel} />
            <div>
              <strong>{d.contact || d.business_name}</strong>
              <small>
                {d.campaign} · {d.provider}
              </small>
              {d.error && <small className="delivery-error">Erreur : {d.error}</small>}
            </div>
            <span>{d.status}</span>
          </div>
        ))}
        {!deliveries.length && <Empty text="Aucune livraison." />}
      </article>
    </section>
  );
}
function Compliance({ rows, add }) {
  const [v, setV] = useState("");
  return (
    <section className="panel">
      <div className="toolbar">
        <div>
          <h2>Liste d'opposition</h2>
          <p>Ces destinations ne seront jamais contactées.</p>
        </div>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (v) {
              await add(v);
              setV("");
            }
          }}
        >
          <input
            required
            placeholder="email ou téléphone"
            value={v}
            onChange={(e) => setV(e.target.value)}
          />
          <button>Bloquer</button>
        </form>
      </div>
      {rows.map((r) => (
        <div className="activity" key={r.id}>
          <ShieldCheck />
          <div>
            <strong>{r.value}</strong>
            <small>{r.reason}</small>
          </div>
        </div>
      ))}
      {!rows.length && <Empty text="La liste d'opposition est vide." />}
    </section>
  );
}
function ContactTable({ rows }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Score</th>
            <th>Décideur</th>
            <th>Entreprise</th>
            <th>Email</th>
            <th>Téléphone</th>
            <th>Statut</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>
                <b className="score">{c.score}</b>
              </td>
              <td>
                <strong>
                  {c.first_name} {c.last_name}
                </strong>
                <small>{c.role}</small>
              </td>
              <td>{c.business_name}</td>
              <td>{c.email || "—"}</td>
              <td>{c.phone || "—"}</td>
              <td>
                <span className={`status ${c.status}`}>
                  {c.opted_out ? "opposition" : c.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <Empty text="Aucun contact." />}
    </div>
  );
}
function Step({ n, channel, text, sub }) {
  return (
    <div className="step-row">
      <span>{n}</span>
      <Channel type={channel} />
      <div>
        <strong>{text}</strong>
        <small>{sub}</small>
      </div>
    </div>
  );
}
function Channel({ type }) {
  return (
    <span className={`channel ${type}`}>
      {type === "email" ? (
        <Mail />
      ) : type === "sms" ? (
        <Phone />
      ) : (
        <MessageCircle />
      )}
    </span>
  );
}
function Empty({ text }) {
  return <div className="empty-row">{text}</div>;
}
function CampaignModal({ form, setForm, close, submit, busy, error }) {
  const field = (k, v) => setForm({ ...form, [k]: v });
  return (
    <div className="overlay">
      <form className="modal" onSubmit={submit}>
        <div className="modal-head">
          <div>
            <p className="eyebrow">NOUVEAU FLUX</p>
            <h2>Créer une campagne</h2>
          </div>
          <button type="button" onClick={close}>
            <X />
          </button>
        </div>
        {error && <div className="login-error">{error}</div>}
        <div className="campaign-journey"><span className="active">1 · Paramètres</span><span className="active">2 · Prospects</span><span>3 · Programmation</span></div>
        <h3 className="form-section-title">1. Définir la campagne</h3>
        <div className="grid3">
          <label>
            Nom
            <input
              required
              value={form.name}
              onChange={(e) => field("name", e.target.value)}
            />
          </label>
          <label>
            Secteur / audience
            <input
              value={form.sector}
              onChange={(e) => field("sector", e.target.value)}
            />
          </label>
          <label>
            Objectif
            <select
              value={form.objective}
              onChange={(e) => field("objective", e.target.value)}
            >
              <option value="book_meeting">Prise de RDV</option>
              <option value="generate_reply">Obtenir une réponse</option>
              <option value="send_demo">Envoyer une démo</option>
              <option value="qualify">Qualifier</option>
            </select>
          </label>
        </div>
        <div className="grid3">
          <label>
            Canal
            <select
              value={form.channel}
              onChange={(e) => {
                const c = e.target.value;
                setForm({
                  ...form,
                  channel: c,
                  message: CHANNEL_MESSAGES[c],
                  subject: c === "email" ? "Une piste pour {business_name}" : "",
                  content_type: "text",
                  provider:
                    c === "email"
                      ? "emelia"
                      : c === "sms"
                        ? "isendpro"
                        : "ambs",
                });
              }}
            >
              <option value="email">Email</option>
              <option value="sms">SMS</option>
              <option value="whatsapp">WhatsApp</option>
            </select>
          </label>
          <label>
            Fournisseur
            <input readOnly value={form.provider} />
          </label>
          <label>
            Calendrier
            <input
              value={form.calendar_url}
              onChange={(e) => field("calendar_url", e.target.value)}
            />
          </label>
        </div>
        <label>
          Tags
          <input
            value={form.tags}
            onChange={(e) => field("tags", e.target.value)}
          />
        </label>
        <h3 className="form-section-title">2. Ajouter les destinataires</h3>
        <div className="campaign-message-source">
          <CheckCircle2 />
          <div><strong>Messages personnalisés déjà prêts</strong><small>Après création, sélectionnez les prospects depuis la page Prospects. La campagne utilisera automatiquement leur message {form.channel === "email" ? "email" : form.channel === "sms" ? "SMS" : "WhatsApp"} validé.</small></div>
        </div>
        <label>
          Vidéo
          <input
            value={form.video_url}
            onChange={(e) => field("video_url", e.target.value)}
          />
        </label>
        <h3 className="form-section-title">3. Envoi immédiat ou programmation</h3>
        <div className="grid3 schedule-grid">
          <label>Date et heure d’envoi
            <input type="datetime-local" value={form.scheduled_at} onChange={(e) => field("scheduled_at", e.target.value)} />
            <small>Laisser vide : aucun envoi programmé. L’envoi partira immédiatement lorsque vous cliquerez sur Envoyer.</small>
          </label>
          <label>Fuseau horaire
            <select value={form.time_zone} onChange={(e) => field("time_zone", e.target.value)}>
              <option value="Europe/Paris">Europe/Paris</option>
              <option value="Africa/Porto-Novo">Bénin · Porto-Novo</option>
              <option value="Africa/Abidjan">Afrique de l’Ouest</option>
            </select>
          </label>
          <div className="review-card"><strong>{form.channel.toUpperCase()}</strong><span>{form.scheduled_at ? "Envoi programmé" : "Brouillon"}</span><small>{form.provider}</small></div>
        </div>
        <div className="modal-actions">
          <button type="button" onClick={close}>
            Annuler
          </button>
          <button className="primary" disabled={busy}>
            {form.scheduled_at ? "Créer et programmer" : "Créer la campagne"}
          </button>
        </div>
      </form>
    </div>
  );
}
createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
