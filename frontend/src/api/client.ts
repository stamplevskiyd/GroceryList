import createClient from "openapi-fetch";
import createQueryClient from "openapi-react-query";
import type { paths } from "./schema.js";

function deviceId(): string {
  try {
    const saved = localStorage.getItem("grocery-device");
    if (saved) return saved;
    const id = crypto.randomUUID();
    localStorage.setItem("grocery-device", id);
    return id;
  } catch {
    return crypto.randomUUID();
  }
}

export const deviceHeaders = { "X-Device-Id": deviceId() };
export const api = createClient<paths>({
  baseUrl: location.origin,
  credentials: "same-origin",
  cache: "no-store",
  headers: deviceHeaders,
});
export const $api = createQueryClient(api);

export function errorMessage(error: unknown): string {
  if (
    error &&
    typeof error === "object" &&
    "message" in error &&
    typeof error.message === "string"
  ) {
    return error.message;
  }
  return "Не удалось связаться с сервером. Попробуйте ещё раз.";
}

export function isUnauthenticated(error: unknown): boolean {
  return (
    !!error &&
    typeof error === "object" &&
    "code" in error &&
    error.code === "not_authenticated"
  );
}
