import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { components } from "../src/api/schema.js";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn();
  vi.stubGlobal("fetch", mock);
  return mock;
});
import { App } from "../src/main.js";

type Item = components["schemas"]["ItemRead"];
const listId = "00000000-0000-4000-8000-000000000001";
const me: components["schemas"]["MeRead"] = {
  id: "00000000-0000-4000-8000-000000000002",
  username: "anna",
  shopping_lists: [{ id: listId, name: "Покупки" }],
};
const milk: Item = {
  id: "00000000-0000-4000-8000-000000000003",
  shopping_list_id: listId,
  name: "Молоко",
  quantity: 2,
  unit: "л",
  note: null,
  tags: [],
  sources: [{ kind: "app" }],
  is_bought: false,
  bought_at: null,
  created_at: "2026-10-04T00:00:00Z",
  updated_at: "2026-10-04T00:00:00Z",
};
class Stream {
  static instances: Stream[] = [];
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(public url: string) {
    Stream.instances.push(this);
  }
}
let loggedIn: boolean;
let items: Item[];
let failAdd: boolean;
let duplicateUser: boolean;
let client: QueryClient;
const writes: Array<{ path: string; body: unknown; device: string | null }> =
  [];

beforeEach(() => {
  vi.stubGlobal("EventSource", Stream);
  loggedIn = false;
  failAdd = false;
  duplicateUser = false;
  items = [];
  writes.length = 0;
  Stream.instances = [];
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  fetchMock.mockImplementation(async (request: Request) => {
    const path = new URL(request.url).pathname;
    const json = (body: unknown, status = 200) =>
      Response.json(body, { status });
    if (path === "/api/auth/login") {
      loggedIn = true;
      return json(me);
    }
    if (path === "/api/auth/register") {
      writes.push({
        path,
        body: await request.json(),
        device: request.headers.get("X-Device-Id"),
      });
      if (duplicateUser)
        return json(
          {
            code: "conflict",
            message: "Пользователь с таким логином уже существует",
          },
          409,
        );
      loggedIn = true;
      return json(me, 201);
    }
    if (!loggedIn)
      return json(
        { code: "not_authenticated", message: "Требуется вход" },
        401,
      );
    if (path === "/api/me") return json(me);
    if (request.method === "GET" && path === "/api/items") return json(items);
    if (request.method === "POST") {
      const body = request.headers.get("content-type")?.includes("json")
        ? await request.json()
        : null;
      writes.push({ path, body, device: request.headers.get("X-Device-Id") });
      if (path === "/api/items/quick-add") {
        if (failAdd)
          return json(
            { code: "invalid_request", message: "Покупку не удалось добавить" },
            422,
          );
        items = [structuredClone(milk)];
        return json({
          parsed: { name: "Молоко", quantity: 2, unit: "л" },
          result: { status: "created", item: items[0] },
        });
      }
      if (path === "/api/items/bought") {
        items = items.map((item) => ({ ...item, is_bought: body.bought }));
        return json(items);
      }
      if (path === "/api/auth/logout") {
        loggedIn = false;
        return new Response(null, { status: 204 });
      }
    }
    throw new Error(`Unexpected request ${request.method} ${path}`);
  });
});
afterEach(() => {
  cleanup();
  client.clear();
  fetchMock.mockReset();
});

test("registration validates confirmation, then opens the new list without a second login", async () => {
  mount();
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", {
      name: "Нет аккаунта? Зарегистрироваться",
    }),
  );
  await user.type(screen.getByLabelText("Логин"), "anna");
  await user.type(screen.getByLabelText("Пароль"), "new-long-password");
  await user.type(
    screen.getByLabelText("Повторите пароль"),
    "different-password",
  );
  await user.click(screen.getByRole("button", { name: "Зарегистрироваться" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Пароли не совпадают",
  );
  expect(writes).toHaveLength(0);
  await user.clear(screen.getByLabelText("Повторите пароль"));
  await user.type(
    screen.getByLabelText("Повторите пароль"),
    "new-long-password",
  );
  await user.click(screen.getByRole("button", { name: "Зарегистрироваться" }));
  await screen.findByRole("heading", { name: "Покупки" });
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    path: "/api/auth/register",
    body: { username: "anna", password: "new-long-password" },
  });
  expect(Object.keys(writes[0].body as object)).toEqual([
    "username",
    "password",
  ]);
  expect(writes[0].device).toBeTruthy();
  expect(
    fetchMock.mock.calls.some(
      ([request]) => new URL(request.url).pathname === "/api/auth/login",
    ),
  ).toBe(false);
});

test("duplicate registration stays on the form and shows the server error", async () => {
  duplicateUser = true;
  mount();
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", {
      name: "Нет аккаунта? Зарегистрироваться",
    }),
  );
  await user.type(screen.getByLabelText("Логин"), "anna");
  await user.type(screen.getByLabelText("Пароль"), "new-long-password");
  await user.type(
    screen.getByLabelText("Повторите пароль"),
    "new-long-password",
  );
  await user.click(screen.getByRole("button", { name: "Зарегистрироваться" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "уже существует",
  );
  expect((screen.getByLabelText("Логин") as HTMLInputElement).value).toBe(
    "anna",
  );
  expect(screen.queryByRole("heading", { name: "Покупки" })).toBeNull();
});

function mount() {
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}
async function signIn() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Логин"), "anna");
  await user.type(screen.getByLabelText("Пароль"), "test-password");
  await user.click(screen.getByRole("button", { name: "Войти" }));
  await screen.findByRole("heading", { name: "Покупки" });
  return user;
}

test("login → quick add → mark bought → logout clears private state and closes SSE", async () => {
  mount();
  const user = await signIn();
  await user.type(
    screen.getByRole("textbox", { name: "Добавить покупку" }),
    "молоко 2 л",
  );
  await user.click(screen.getByRole("button", { name: "Добавить покупку" }));
  const checkbox = await screen.findByRole("checkbox", {
    name: "Отметить купленным: Молоко",
  });
  expect(writes[0]).toMatchObject({
    path: "/api/items/quick-add",
    body: { text: "молоко 2 л", shopping_list_id: listId, tags: [] },
  });
  expect(writes[0].device).toBeTruthy();
  await waitFor(() =>
    expect((checkbox as HTMLInputElement).disabled).toBe(false),
  );
  await user.click(checkbox);
  await screen.findByRole("heading", { name: "Всё куплено" });
  expect(writes[1]).toMatchObject({
    path: "/api/items/bought",
    body: { shopping_list_id: listId, ids: [milk.id], bought: true },
  });
  await waitFor(() =>
    expect(
      (screen.getByRole("button", { name: "Выйти" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false),
  );
  await user.click(screen.getByRole("button", { name: "Выйти" }));
  await screen.findByLabelText("Логин");
  expect(screen.queryByText("Молоко")).toBeNull();
  expect(Stream.instances[0].close).toHaveBeenCalled();
});

test("failed add keeps the draft and does not invent a successful item", async () => {
  loggedIn = true;
  failAdd = true;
  mount();
  const user = userEvent.setup();
  const field = await screen.findByRole("textbox", {
    name: "Добавить покупку",
  });
  await user.type(field, "молоко 2 л");
  await user.click(screen.getByRole("button", { name: "Добавить покупку" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Покупку не удалось добавить",
  );
  expect((field as HTMLInputElement).value).toBe("молоко 2 л");
  expect(screen.queryByRole("checkbox")).toBeNull();
});

test("SSE reloads server state and renders item names as text", async () => {
  loggedIn = true;
  mount();
  await screen.findByRole("heading", { name: "Покупки" });
  await waitFor(() => expect(Stream.instances).toHaveLength(1));
  items = [{ ...milk, name: "<img src=x onerror=alert(1)>" }];
  act(() => Stream.instances[0].onmessage?.());
  await screen.findByText("<img src=x onerror=alert(1)>");
  expect(document.querySelector("img")).toBeNull();
  expect(Stream.instances[0].url).toContain(listId);
});
