import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
  fireEvent,
} from "@testing-library/react";
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
let failPatch: boolean;
let client: QueryClient;
const writes: Array<{
  path: string;
  body: unknown;
  device: string | null;
}> = [];

beforeEach(() => {
  vi.stubGlobal("EventSource", Stream);
  loggedIn = false;
  failAdd = false;
  duplicateUser = false;
  failPatch = false;
  // JSDOM has no native dialog top layer; model its open state for form tests.
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {
      configurable: true,
      value: function (this: HTMLDialogElement) {
        this.setAttribute("open", "");
      },
    },
    close: {
      configurable: true,
      value: function (this: HTMLDialogElement) {
        this.removeAttribute("open");
      },
    },
  });
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
    if (request.method === "GET" && path === "/api/tags")
      return json([
        { id: "breakfast-tag", name: "Завтрак", open_count: 0 },
        ...items.flatMap((item) =>
          item.tags.map((tag) => ({ ...tag, open_count: 1 })),
        ),
      ]);
    if (request.method === "PATCH" && path.startsWith("/api/items/")) {
      const body =
        (await request.json()) as components["schemas"]["ItemUpdate"];
      writes.push({
        path,
        body,
        device: request.headers.get("X-Device-Id"),
      });
      if (failPatch)
        return json(
          {
            code: "conflict",
            message: "Позиция с таким названием уже существует",
          },
          409,
        );
      const id = path.split("/").at(-1);
      items = items.map((item) =>
        item.id === id
          ? {
              ...item,
              name: body.name ?? item.name,
              quantity:
                "quantity" in body
                  ? body.quantity == null
                    ? null
                    : Number(body.quantity)
                  : item.quantity,
              unit: "unit" in body ? (body.unit ?? null) : item.unit,
              note: "note" in body ? (body.note ?? null) : item.note,
              tags: body.tags
                ? body.tags.map((name, index) => ({
                    id: `tag-${index}`,
                    name,
                  }))
                : item.tags,
              updated_at: "2026-10-04T01:00:00Z",
            }
          : item,
      );
      return json(items.find((item) => item.id === id));
    }
    if (request.method === "DELETE" && path.startsWith("/api/items/")) {
      writes.push({
        path,
        body: null,
        device: request.headers.get("X-Device-Id"),
      });
      items = items.filter((item) => item.id !== path.split("/").at(-1));
      return new Response(null, { status: 204 });
    }
    if (request.method === "POST") {
      const body = request.headers.get("content-type")?.includes("json")
        ? await request.json()
        : null;
      writes.push({
        path,
        body,
        device: request.headers.get("X-Device-Id"),
      });
      if (path === "/api/items/quick-add") {
        if (failAdd)
          return json(
            {
              code: "invalid_request",
              message: "Покупку не удалось добавить",
            },
            422,
          );
        items = [structuredClone(milk)];
        return json({
          parsed: { name: "Молоко", quantity: 2, unit: "л" },
          result: { status: "created", item: items[0] },
        });
      }
      if (path === "/api/items/bought") {
        items = items.map((item) =>
          body.ids.includes(item.id)
            ? { ...item, is_bought: body.bought }
            : item,
        );
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
  vi.restoreAllMocks();
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

async function openCard(item: Item = milk) {
  loggedIn = true;
  items = [structuredClone(item)];
  mount();
  const user = userEvent.setup();
  const opener = await screen.findByRole("button", {
    name: `Открыть карточку: ${item.name}`,
  });
  await user.click(opener);
  const dialog = await screen.findByRole("dialog", {
    name: "Карточка покупки",
  });
  return { user, card: within(dialog), dialog, opener };
}

test("card saves name, decimal quantity, chosen unit, existing/new tags and note", async () => {
  const { user, card } = await openCard();
  await user.clear(card.getByLabelText("Название"));
  await user.type(card.getByLabelText("Название"), "Мука");
  await user.clear(card.getByLabelText("Количество"));
  await user.type(card.getByLabelText("Количество"), "1,5");
  await user.selectOptions(card.getByLabelText("Единица"), "кг");
  await user.click(await card.findByRole("button", { name: "Завтрак" }));
  await user.type(card.getByLabelText("Теги"), "Выпечка");
  await user.type(card.getByLabelText("Заметка"), "Для блинов");
  await user.click(card.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(writes[0]).toMatchObject({
    path: `/api/items/${milk.id}`,
    body: {
      name: "Мука",
      quantity: "1.5",
      unit: "кг",
      tags: ["Завтрак", "Выпечка"],
      note: "Для блинов",
    },
  });
  expect(writes[0].device).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Открыть карточку: Мука" }),
  ).toBeTruthy();
  expect(document.body.classList.contains("item-sheet-open")).toBe(false);
});

test("clearing optional fields sends nulls and an empty tag list", async () => {
  const { user, card } = await openCard({
    ...milk,
    note: "Без лактозы",
    tags: [{ id: "dairy", name: "Молочное" }],
  });
  await user.clear(card.getByLabelText("Количество"));
  await user.selectOptions(card.getByLabelText("Единица"), "");
  await user.clear(card.getByLabelText("Заметка"));
  await user.click(card.getByRole("button", { name: "Убрать тег «Молочное»" }));
  await user.click(card.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(writes[0].body).toEqual({
    quantity: null,
    unit: null,
    note: null,
    tags: [],
  });
});

test("a failed patch preserves the draft and permits retry", async () => {
  failPatch = true;
  const { user, card } = await openCard();
  await user.clear(card.getByLabelText("Название"));
  await user.type(card.getByLabelText("Название"), "Кефир");
  await user.click(card.getByRole("button", { name: "Сохранить" }));
  expect((await card.findByRole("alert")).textContent).toContain(
    "уже существует",
  );
  expect((card.getByLabelText("Название") as HTMLInputElement).value).toBe(
    "Кефир",
  );
  failPatch = false;
  await user.click(card.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(items[0].name).toBe("Кефир");
});

test("SSE does not erase a draft and a note edit does not overwrite a remote quantity", async () => {
  const { user, card } = await openCard();
  await user.type(card.getByLabelText("Заметка"), "К утру");
  items = [{ ...milk, quantity: 7, updated_at: "2026-10-04T00:30:00Z" }];
  act(() => Stream.instances[0].onmessage?.());
  await card.findByText(/Позиция обновилась/);
  expect((card.getByLabelText("Заметка") as HTMLTextAreaElement).value).toBe(
    "К утру",
  );
  await user.click(card.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(writes[0].body).toEqual({ note: "К утру" });
  expect(items[0].quantity).toBe(7);
});

test("Escape and close protect unsaved input, cancel writes nothing and restores focus", async () => {
  const { user, card, dialog, opener } = await openCard();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.type(card.getByLabelText("Заметка"), "Не сохранять");
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  expect(confirm).toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeTruthy();
  confirm.mockReturnValue(true);
  await user.click(card.getByRole("button", { name: "Закрыть карточку" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(writes).toHaveLength(0);
  expect(document.activeElement).toBe(opener);
});

test("card deletion requires confirmation and removes the item", async () => {
  const { user, card } = await openCard();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.click(card.getByRole("button", { name: "Удалить покупку" }));
  expect(writes).toHaveLength(0);
  confirm.mockReturnValue(true);
  await user.click(card.getByRole("button", { name: "Удалить покупку" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(items).toHaveLength(0);
  expect(writes[0].path).toBe(`/api/items/${milk.id}`);
});

test("invalid quantity stays local; a custom unit can then be saved", async () => {
  const { user, card } = await openCard();
  await user.clear(card.getByLabelText("Количество"));
  await user.type(card.getByLabelText("Количество"), "0");
  await user.click(card.getByRole("button", { name: "Сохранить" }));
  expect((await card.findByRole("alert")).textContent).toContain("больше нуля");
  expect(writes).toHaveLength(0);
  await user.clear(card.getByLabelText("Количество"));
  await user.type(card.getByLabelText("Количество"), "3");
  await user.selectOptions(card.getByLabelText("Единица"), "custom");
  await user.type(card.getByLabelText("Своя единица"), "бутылка");
  await user.click(card.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(writes[0].body).toEqual({ quantity: "3", unit: "бутылка" });
});

test("remote deletion disables saving without discarding the visible draft", async () => {
  const { user, card } = await openCard();
  await user.type(card.getByLabelText("Заметка"), "Черновик");
  items = [];
  act(() => Stream.instances[0].onmessage?.());
  expect((await card.findByRole("alert")).textContent).toContain("уже удалена");
  expect(
    (card.getByRole("button", { name: "Сохранить" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect((card.getByLabelText("Заметка") as HTMLTextAreaElement).value).toBe(
    "Черновик",
  );
});

const breakfast = { id: "breakfast", name: "Завтрак" };
const dairy = { id: "dairy", name: "Молочное" };
async function openGroupedList() {
  loggedIn = true;
  items = [
    { ...structuredClone(milk), tags: [breakfast, dairy] },
    {
      ...structuredClone(milk),
      id: "bread",
      name: "Хлеб",
      tags: [breakfast],
    },
    { ...structuredClone(milk), id: "salt", name: "Соль" },
  ];
  mount();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "По тегам" }));
  await screen.findByRole("region", { name: "Завтрак" });
  return user;
}

test("grouped view repeats multi-tag items while totals and the flat view remain unique", async () => {
  const user = await openGroupedList();
  expect(screen.getByText("3 к покупке · 0 куплено")).toBeTruthy();
  expect(
    screen.getAllByRole("button", { name: "Открыть карточку: Молоко" }),
  ).toHaveLength(2);
  expect(
    within(screen.getByRole("region", { name: "Завтрак" })).getAllByRole(
      "listitem",
    ),
  ).toHaveLength(2);
  expect(
    within(screen.getByRole("region", { name: "Молочное" })).getAllByRole(
      "listitem",
    ),
  ).toHaveLength(1);
  expect(
    within(screen.getByRole("region", { name: "Без тега" })).getByRole(
      "button",
      { name: "Открыть карточку: Соль" },
    ),
  ).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Списком" }));
  expect(screen.queryByRole("region", { name: "Завтрак" })).toBeNull();
  expect(
    screen.getAllByRole("button", { name: "Открыть карточку: Молоко" }),
  ).toHaveLength(1);
  expect(
    screen
      .getByRole("button", { name: "Списком" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  expect(writes).toHaveLength(0);
});

test("buying from one group removes every copy; restoring returns it to both groups", async () => {
  const user = await openGroupedList();
  await user.click(
    within(screen.getByRole("region", { name: "Молочное" })).getByRole(
      "checkbox",
      { name: "Отметить купленным: Молоко" },
    ),
  );
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: "Молочное" })).toBeNull(),
  );
  expect(
    screen.queryByRole("checkbox", { name: "Отметить купленным: Молоко" }),
  ).toBeNull();
  expect(screen.getByText("2 к покупке · 1 куплено")).toBeTruthy();
  expect(writes[0].body).toEqual({
    shopping_list_id: listId,
    ids: [milk.id],
    bought: true,
  });
  await user.click(screen.getByText("Куплено"));
  const restore = screen.getByRole("checkbox", {
    name: "Вернуть в покупки: Молоко",
  });
  await waitFor(() =>
    expect((restore as HTMLInputElement).disabled).toBe(false),
  );
  await user.click(restore);
  await screen.findByRole("region", { name: "Молочное" });
  expect(
    screen.getAllByRole("checkbox", { name: "Отметить купленным: Молоко" }),
  ).toHaveLength(2);
  expect(screen.getByText("3 к покупке · 0 куплено")).toBeTruthy();
});

test("tag filters limit groups and live updates move purchases between them", async () => {
  const user = await openGroupedList();
  const filters = within(
    screen.getByRole("navigation", { name: "Фильтр по тегам" }),
  );
  await user.click(filters.getByRole("button", { name: "Молочное" }));
  expect(screen.queryByRole("region", { name: "Завтрак" })).toBeNull();
  expect(screen.queryByRole("region", { name: "Без тега" })).toBeNull();
  expect(screen.getByText("1 к покупке · 0 куплено")).toBeTruthy();
  await user.click(filters.getByRole("button", { name: "Завтрак" }));
  expect(
    screen.getAllByRole("button", { name: "Открыть карточку: Молоко" }),
  ).toHaveLength(2);
  expect(screen.getByText("2 к покупке · 0 куплено")).toBeTruthy();
  await user.click(filters.getByRole("button", { name: "Все" }));
  items = items.map((item) =>
    item.id === milk.id ? { ...item, tags: [] } : item,
  );
  act(() => Stream.instances[0].onmessage?.());
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: "Молочное" })).toBeNull(),
  );
  expect(
    within(screen.getByRole("region", { name: "Без тега" })).getByRole(
      "button",
      { name: "Открыть карточку: Молоко" },
    ),
  ).toBeTruthy();
  expect(
    within(screen.getByRole("region", { name: "Завтрак" })).queryByRole(
      "button",
      { name: "Открыть карточку: Молоко" },
    ),
  ).toBeNull();
  expect(writes).toHaveLength(0);
});

test("editing or deleting a grouped purchase changes the one shared item", async () => {
  const user = await openGroupedList();
  await user.click(
    within(screen.getByRole("region", { name: "Молочное" })).getByRole(
      "button",
      { name: "Открыть карточку: Молоко" },
    ),
  );
  const card = within(screen.getByRole("dialog"));
  await user.clear(card.getByLabelText("Название"));
  await user.type(card.getByLabelText("Название"), "Кефир");
  await user.click(card.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(
    screen.getAllByRole("button", { name: "Открыть карточку: Кефир" }),
  ).toHaveLength(2);
  expect(writes[0].body).toEqual({ name: "Кефир" });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  await user.click(
    within(screen.getByRole("region", { name: "Завтрак" })).getByRole(
      "button",
      { name: "Удалить: Кефир" },
    ),
  );
  await waitFor(() =>
    expect(
      screen.queryAllByRole("button", { name: "Открыть карточку: Кефир" }),
    ).toHaveLength(0),
  );
  expect(screen.getByText("2 к покупке · 0 куплено")).toBeTruthy();
  expect(items.map((item) => item.name)).toEqual(["Хлеб", "Соль"]);
});

test("tag management keeps live updates and returns to the shopping list", async () => {
  loggedIn = true;
  items = [
    { ...structuredClone(milk), tags: [{ id: "dairy", name: "Молочное" }] },
  ];
  mount();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Теги" }));
  await screen.findByRole("heading", { name: "Теги" });
  await screen.findByText("Молочное", { selector: "summary > span" });
  expect(
    screen.queryByRole("textbox", { name: "Добавить покупку" }),
  ).toBeNull();
  items = [{ ...milk, tags: [{ id: "dairy", name: "Молочные продукты" }] }];
  act(() => Stream.instances[0].onmessage?.());
  await screen.findByText("Молочные продукты", { selector: "summary > span" });
  await user.click(screen.getByRole("button", { name: "← К списку" }));
  await screen.findByRole("heading", { name: "Покупки" });
  expect(
    screen.getByRole("button", { name: "Открыть карточку: Молоко" }),
  ).toBeTruthy();
  expect(Stream.instances).toHaveLength(1);
  expect(Stream.instances[0].close).not.toHaveBeenCalled();
});
