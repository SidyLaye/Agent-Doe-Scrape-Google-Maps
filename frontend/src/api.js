const BASE = import.meta.env.VITE_API_URL || "";
async function request(path, options = {}) {
  const token = localStorage.getItem("ambs_token");
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${BASE}${path}`, { ...options, headers });
  if (response.status === 401 && path !== "/api/auth/login") {
    localStorage.removeItem("ambs_token");
    window.dispatchEvent(new Event("ambs:logout"));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Erreur ${response.status}`);
  }
  return response.json();
}
export const api = {
  login: (email, password) =>
    request("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  me: () => request("/api/auth/me"),
  prospects: (search = "") =>
    request(`/api/prospects?search=${encodeURIComponent(search)}`),
  prospectingJobs: () => request("/api/prospecting/jobs"),
  startProspecting: (data) =>
    request("/api/prospecting/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  addProspectsToCampaign: (campaign_id, prospect_ids) =>
    request("/api/prospects/add-to-campaign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ campaign_id, prospect_ids }),
    }),
  importProspects: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/prospects/import", { method: "POST", body: form });
  },
  updateProspectMessages: (id, data) =>
    request(`/api/prospects/${id}/messages`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  generateMessage: (data) =>
    request("/api/ai/generate-message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  config: () => request("/api/config"),
  setMode: (dry_run, confirm_live = false) =>
    request("/api/config/mode", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run, confirm_live }),
    }),
  campaigns: () => request("/api/campaigns"),
  allContacts: (search = "") =>
    request(`/api/contacts?search=${encodeURIComponent(search)}`),
  conversations: () => request("/api/conversations"),
  deliveries: () => request("/api/deliveries"),
  suppressions: () => request("/api/suppressions"),
  suppress: (value) =>
    request("/api/suppressions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value, reason: "manual" }),
    }),
  handover: (id, paused) =>
    request(`/api/conversations/${id}/handover`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paused }),
    }),
  sheets: () => request("/api/google-sheets"),
  sheetMetadata: (spreadsheet) =>
    request(
      `/api/google-sheets/metadata?spreadsheet=${encodeURIComponent(spreadsheet)}`,
    ),
  sheetPreview: (spreadsheet, sheet) =>
    request(
      `/api/google-sheets/preview?spreadsheet=${encodeURIComponent(spreadsheet)}&sheet_name=${encodeURIComponent(sheet)}&limit=100`,
    ),
  importSheet: (campaign, spreadsheet, sheet) =>
    request(`/api/campaigns/${campaign}/contacts/import-sheet`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spreadsheet, sheet_name: sheet }),
    }),
  create: (data) =>
    request("/api/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  contacts: (id) => request(`/api/campaigns/${id}/contacts`),
  preview: (id) => request(`/api/campaigns/${id}/preview`),
  analytics: () => request("/api/analytics"),
  sequence: (id) => request(`/api/campaigns/${id}/sequence`),
  addStep: (id, data) =>
    request(`/api/campaigns/${id}/sequence`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  upload: (id, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/campaigns/${id}/contacts/import`, {
      method: "POST",
      body: form,
    });
  },
  send: (id, limit = 10, confirm_live = false) =>
    request(`/api/campaigns/${id}/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit, confirm_live }),
    }),
  pauseCampaign: (id) => request(`/api/campaigns/${id}/pause`, { method: "POST" }),
  resumeCampaign: (id) => request(`/api/campaigns/${id}/resume`, { method: "POST" }),
  scheduleCampaign: (id, scheduled_at, confirm_live = false) =>
    request(`/api/campaigns/${id}/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scheduled_at, confirm_live }),
    }),
};
