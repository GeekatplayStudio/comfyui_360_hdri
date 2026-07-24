import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

function notify(message, type = "info") {
	const toast = app.extensionManager?.toast;
	if (toast?.add) {
		toast.add({ severity: type, summary: "Geekatplay Credentials", detail: message, life: 5000 });
	} else {
		console[type === "error" ? "error" : "log"](`[Geekatplay] ${message}`);
	}
}

async function responseJson(response) {
	const payload = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(payload.message || `${response.status} ${response.statusText}`);
	return payload;
}

function credentialDialog(defaultName = "Meshy") {
	return new Promise((resolve) => {
		const overlay = document.createElement("div");
		overlay.style.cssText = "position:fixed;inset:0;z-index:10000;background:#0009;display:grid;place-items:center";
		const dialog = document.createElement("form");
		dialog.style.cssText = "width:min(420px,90vw);padding:20px;border-radius:10px;background:var(--comfy-menu-bg,#242424);color:var(--input-text,#eee);box-shadow:0 10px 35px #000";
		dialog.innerHTML = `
			<h3 style="margin:0 0 16px">Save API credential</h3>
			<label style="display:block;margin-bottom:12px">Name
				<input name="name" autocomplete="off" maxlength="80" value="${defaultName}" style="box-sizing:border-box;width:100%;margin-top:5px;padding:8px">
			</label>
			<label style="display:block;margin-bottom:16px">Secret
				<input name="secret" type="password" autocomplete="new-password" maxlength="8192" style="box-sizing:border-box;width:100%;margin-top:5px;padding:8px">
			</label>
			<div style="display:flex;justify-content:flex-end;gap:8px">
				<button type="button" data-cancel>Cancel</button><button type="submit">Save to OS vault</button>
			</div>`;
		overlay.append(dialog);
		document.body.append(overlay);
		const close = (value) => { overlay.remove(); resolve(value); };
		dialog.querySelector("[data-cancel]").onclick = () => close(null);
		overlay.onclick = (event) => { if (event.target === overlay) close(null); };
		dialog.onsubmit = (event) => {
			event.preventDefault();
			const data = new FormData(dialog);
			close({ name: data.get("name")?.trim(), value: data.get("secret")?.trim() });
		};
		setTimeout(() => dialog.elements.secret.focus(), 0);
	});
}

function updateCredentialWidget(node, keys, selected) {
	const widget = node.widgets?.find((item) => item.name === "service_name");
	if (!widget) return;
	const values = ["None", ...keys];
	widget.options = { ...widget.options, values };
	widget.value = values.includes(selected) ? selected : "None";
	node.setDirtyCanvas(true, true);
}

app.registerExtension({
	name: "Geekatplay.CredentialManager.v2",
	async beforeRegisterNodeDef(nodeType, nodeData) {
		if (nodeData.name !== "Geekatplay_ApiKey_Manager") return;
		const original = nodeType.prototype.onNodeCreated;
		nodeType.prototype.onNodeCreated = function () {
			const result = original?.apply(this, arguments);
			const refresh = async (selected = this.widgets?.find((w) => w.name === "service_name")?.value) => {
				const payload = await responseJson(await api.fetchApi("/geekatplay/credentials"));
				updateCredentialWidget(this, payload.keys, selected);
			};
			this.addWidget("button", "Save credential", null, async () => {
				try {
					const credential = await credentialDialog();
					if (!credential) return;
					if (!credential.name || !credential.value) throw new Error("Name and secret are required");
					const payload = await responseJson(await api.fetchApi("/geekatplay/credentials", {
						method: "POST",
						headers: { "Content-Type": "application/json" },
						body: JSON.stringify(credential),
					}));
					updateCredentialWidget(this, payload.keys, credential.name);
					notify("Credential saved in the operating-system vault.", "success");
				} catch (error) {
					notify(error.message, "error");
				}
			});
			this.addWidget("button", "Delete selected", null, async () => {
				const selected = this.widgets?.find((w) => w.name === "service_name")?.value;
				if (!selected || selected === "None" || !confirm(`Delete credential “${selected}”?`)) return;
				try {
					const payload = await responseJson(await api.fetchApi(`/geekatplay/credentials/${encodeURIComponent(selected)}`, { method: "DELETE" }));
					updateCredentialWidget(this, payload.keys, "None");
					notify("Credential deleted.", "success");
				} catch (error) {
					notify(error.message, "error");
				}
			});
			this.addWidget("button", "Refresh credentials", null, () => refresh().catch((error) => notify(error.message, "error")));
			refresh().catch((error) => notify(error.message, "error"));
			return result;
		};
	},
});
