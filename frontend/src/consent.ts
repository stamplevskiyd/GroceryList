import type { components } from "./api/schema.js";
import { api, deviceHeaders, errorMessage } from "./api/client.js";
import "./styles/consent.css";

type Me = components["schemas"]["MeRead"];

function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error || result.data === undefined) {
    const error = result.error;
    const message =
      error && typeof error === "object" && "error_description" in error
        ? String(error.error_description)
        : errorMessage(error);
    throw new Error(message);
  }
  return result.data;
}

function element<T extends HTMLElement>(selector: string): T {
  const found = document.querySelector<T>(selector);
  if (!found) throw new Error(`Missing element: ${selector}`);
  return found;
}

async function startConsent(): Promise<void> {
  element("#landing").hidden = true;
  const template = element<HTMLTemplateElement>("#consent-template");
  document.body.append(template.content.cloneNode(true));
  document.title = "Разрешить доступ — GroceryList";
  const status = element("#consent-status");
  const login = element<HTMLFormElement>("#login-form");
  const decision = element<HTMLFormElement>("#decision-form");
  const requestId = new URLSearchParams(location.search).get("request");
  if (!requestId || !/^[0-9a-f-]{36}$/i.test(requestId)) {
    status.textContent =
      "Откройте подключение GroceryList из вашего ассистента. Эта ссылка неполная.";
    return;
  }
  let busy = false;

  function showError(error: unknown): void {
    status.textContent =
      error instanceof Error
        ? error.message
        : "Не удалось подключиться к серверу.";
    status.setAttribute("role", "alert");
  }

  async function showDecision(me: Me): Promise<void> {
    const data = unwrap(
      await api.GET("/api/oauth/requests/{id}", {
        params: { path: { id: requestId! } },
        cache: "no-store",
      }),
    );
    element("#client-name").textContent = data.client_name;
    element("#redirect-host").textContent = data.redirect_host;
    element("#redirect-address").textContent = data.redirect_uri;
    element("#signed-in-user").textContent = me.username;
    element("#loopback-notice").hidden = !data.loopback;
    element("#offline-notice").hidden = !data.scopes.includes("offline_access");
    login.hidden = true;
    decision.hidden = false;
    status.textContent = "";
    element<HTMLButtonElement>("#deny-access").focus();
  }

  login.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    const button = element<HTMLButtonElement>("#sign-in");
    const password = element<HTMLInputElement>("#password");
    button.disabled = true;
    status.textContent = "Входим…";
    try {
      const me = unwrap(
        await api.POST("/api/auth/login", {
          params: { header: deviceHeaders },
          body: {
            username: element<HTMLInputElement>("#username").value,
            password: password.value,
          },
        }),
      );
      password.value = "";
      await showDecision(me);
    } catch (error) {
      showError(error);
    } finally {
      busy = false;
      button.disabled = false;
    }
  });

  decision.addEventListener("submit", async (event: SubmitEvent) => {
    event.preventDefault();
    if (busy || !(event.submitter instanceof HTMLButtonElement)) return;
    busy = true;
    const buttons = decision.querySelectorAll<HTMLButtonElement>("button");
    buttons.forEach((button) => {
      button.disabled = true;
    });
    status.textContent = "Сохраняем решение…";
    try {
      const result = unwrap(
        await api.POST("/api/oauth/consent", {
          params: { header: deviceHeaders },
          body: {
            request_id: requestId,
            allow: event.submitter.value === "allow",
          },
        }),
      );
      // The server validates the registered callback, including loopback clients.
      location.assign(result.redirect_url);
    } catch (error) {
      showError(error);
      buttons.forEach((button) => {
        button.disabled = false;
      });
      busy = false;
    }
  });

  try {
    const result = await api.GET("/api/me", { cache: "no-store" });
    if (result.response.status === 401) {
      login.hidden = false;
      status.textContent = "";
      element<HTMLInputElement>("#username").focus();
    } else {
      await showDecision(unwrap(result));
    }
  } catch (error) {
    showError(error);
  }
}

if (location.pathname.replace(/\/$/, "") === "/consent") {
  void startConsent();
}
