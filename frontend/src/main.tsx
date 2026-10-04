import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import {
  $api,
  deviceHeaders,
  errorMessage,
  isUnauthenticated,
} from "./api/client.js";
import type { components } from "./api/schema.js";
import "./consent.js";
import "./styles/app.css";

type Me = components["schemas"]["MeRead"];
type Item = components["schemas"]["ItemRead"];
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function Brand() {
  return (
    <div className="app-brand">
      <span className="brand-mark" aria-hidden="true">
        ✓
      </span>{" "}
      GroceryList
    </div>
  );
}

function Login({ onLogin }: { onLogin: (me: Me) => void }) {
  const login = $api.useMutation("post", "/api/auth/login");
  const registration = $api.useMutation("post", "/api/auth/register");
  const [registering, setRegistering] = useState(
    () => new URLSearchParams(location.search).get("register") === "1",
  );
  const [validationError, setValidationError] = useState("");
  const submitting = useRef(false);
  const busy = login.isPending || registration.isPending;
  const active = registering ? registration : login;
  return (
    <div className="app-login">
      <Brand />
      <h1>
        Всё нужное —<br />в одном списке.
      </h1>
      <p className="app-muted">
        Покупки для ваших планов на ужин и походов в магазин.
      </p>
      <form
        key={registering ? "register" : "login"}
        onSubmit={async (event) => {
          event.preventDefault();
          if (submitting.current) return;
          const form = event.currentTarget;
          const values = new FormData(form);
          setValidationError("");
          if (
            registering &&
            values.get("password") !== values.get("confirm_password")
          ) {
            setValidationError("Пароли не совпадают");
            return;
          }
          submitting.current = true;
          try {
            const me = await active.mutateAsync({
              params: { header: deviceHeaders },
              body: {
                username: String(values.get("username")),
                password: String(values.get("password")),
              },
            });
            form.reset();
            onLogin(me);
          } catch {
            /* Display the typed mutation error below. */
          } finally {
            submitting.current = false;
          }
        }}
      >
        <label>
          Логин
          <input
            name="username"
            autoComplete="username"
            required
            maxLength={64}
            autoFocus
          />
        </label>
        <label>
          Пароль
          <input
            name="password"
            type="password"
            autoComplete={registering ? "new-password" : "current-password"}
            minLength={registering ? 8 : undefined}
            maxLength={registering ? 128 : undefined}
            aria-describedby={registering ? "password-hint" : undefined}
            required
          />
        </label>
        {registering && (
          <>
            <p id="password-hint" className="app-muted app-small">
              От 8 до 128 символов. После регистрации у вас появится личный
              список покупок.
            </p>
            <label>
              Повторите пароль
              <input
                name="confirm_password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                maxLength={128}
                required
              />
            </label>
          </>
        )}
        {(validationError || active.isError) && (
          <p role="alert" className="app-error">
            {validationError || errorMessage(active.error)}
          </p>
        )}
        <button className="app-primary" disabled={busy}>
          {busy
            ? registering
              ? "Создаём аккаунт…"
              : "Входим…"
            : registering
              ? "Зарегистрироваться"
              : "Войти"}
        </button>
      </form>
      <button
        className="app-auth-switch"
        disabled={busy}
        onClick={() => {
          setRegistering((value) => !value);
          setValidationError("");
          login.reset();
          registration.reset();
        }}
      >
        {registering
          ? "Уже есть аккаунт? Войти"
          : "Нет аккаунта? Зарегистрироваться"}
      </button>
    </div>
  );
}

function Shopping({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const cache = useQueryClient();
  const [listId, setListId] = useState(me.shopping_lists[0]?.id ?? "");
  const [draft, setDraft] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const lock = useRef(false);
  const input = useRef<HTMLInputElement>(null);
  const itemsQuery = $api.useQuery(
    "get",
    "/api/items",
    {
      params: { query: { shopping_list_id: listId, include_bought: true } },
    },
    { enabled: !!listId },
  );
  const add = $api.useMutation("post", "/api/items/quick-add");
  const bought = $api.useMutation("post", "/api/items/bought");
  const remove = $api.useMutation("delete", "/api/items/{id}");
  const clear = $api.useMutation("post", "/api/items/clear-bought");
  const logout = $api.useMutation("post", "/api/auth/logout");

  const refresh = () =>
    cache.invalidateQueries({ queryKey: ["get", "/api/items"] });
  useEffect(() => {
    if (!listId) return;
    setConnected(false);
    const stream = new EventSource(
      `/api/events?shopping_list_id=${encodeURIComponent(listId)}`,
    );
    stream.onopen = () => {
      setConnected(true);
      void cache.invalidateQueries({ queryKey: ["get", "/api/items"] });
    };
    stream.onmessage = () => {
      void cache.invalidateQueries({ queryKey: ["get", "/api/items"] });
    };
    stream.onerror = () => {
      setConnected(false);
      void cache.invalidateQueries({ queryKey: ["get", "/api/items"] });
    };
    return () => stream.close();
  }, [listId, cache]);
  useEffect(() => {
    if (isUnauthenticated(itemsQuery.error)) onLogout();
  }, [itemsQuery.error, onLogout]);

  async function action(run: () => Promise<unknown>, success?: () => void) {
    if (lock.current) return;
    lock.current = true;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      await run();
      success?.();
      await refresh();
    } catch (reason) {
      if (isUnauthenticated(reason)) onLogout();
      else setError(errorMessage(reason));
    } finally {
      lock.current = false;
      setWorking(false);
    }
  }

  const items = itemsQuery.data ?? [];
  const tags = [
    ...new Map(
      items.flatMap((item) => item.tags).map((tag) => [tag.name, tag]),
    ).values(),
  ];
  const visible = items.filter(
    (item) =>
      !selectedTags.length ||
      item.tags.some((tag) => selectedTags.includes(tag.name)),
  );
  const pending = visible.filter((item) => !item.is_bought);
  const completed = visible.filter((item) => item.is_bought);
  const totalCompleted = items.filter((item) => item.is_bought).length;

  function row(item: Item) {
    const quantity = [
      item.quantity === null
        ? ""
        : new Intl.NumberFormat("ru").format(item.quantity),
      item.unit,
    ]
      .filter(Boolean)
      .join(" ");
    return (
      <li
        key={item.id}
        className={`app-row ${item.is_bought ? "is-bought" : ""}`}
      >
        <input
          className="app-checkbox"
          type="checkbox"
          checked={item.is_bought}
          disabled={working}
          aria-label={`${item.is_bought ? "Вернуть в покупки" : "Отметить купленным"}: ${item.name}`}
          onChange={() =>
            void action(() =>
              bought.mutateAsync({
                params: { header: deviceHeaders },
                body: {
                  shopping_list_id: listId,
                  ids: [item.id],
                  bought: !item.is_bought,
                },
              }),
            )
          }
        />
        <div className="app-item-text">
          <div className="app-item-title">
            <span>{item.name}</span>
            {quantity && <span className="app-quantity">{quantity}</span>}
          </div>
          {!!item.tags.length && (
            <div className="app-item-tags">
              {item.tags.map((tag) => (
                <span key={tag.id}>{tag.name}</span>
              ))}
            </div>
          )}
          {item.note && <p className="app-small app-muted">{item.note}</p>}
          {item.sources
            .filter((source) => source.kind === "mcp")
            .map((source, index) => (
              <span className="app-source" key={index}>
                добавил {source.client_name}
              </span>
            ))}
        </div>
        <button
          className="app-delete"
          aria-label={`Удалить: ${item.name}`}
          title="Удалить"
          disabled={working}
          onClick={() => {
            if (confirm(`Удалить «${item.name}» из списка?`))
              void action(() =>
                remove.mutateAsync({
                  params: { header: deviceHeaders, path: { id: item.id } },
                }),
              );
          }}
        >
          ×
        </button>
      </li>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <Brand />
        <div className="app-account">
          <span>{me.username}</span>
          <button
            disabled={working}
            onClick={() =>
              void action(
                () => logout.mutateAsync({ params: { header: deviceHeaders } }),
                onLogout,
              )
            }
          >
            Выйти
          </button>
        </div>
      </header>
      <div className="app-heading">
        <div>
          <p className="app-eyebrow">ПОД РУКОЙ</p>
          <h1>
            {me.shopping_lists.find((list) => list.id === listId)?.name ??
              "Покупки"}
          </h1>
        </div>
        <button
          className="app-refresh"
          onClick={() => void refresh()}
          disabled={itemsQuery.isFetching}
        >
          Обновить
        </button>
      </div>
      {me.shopping_lists.length > 1 && (
        <label className="app-list-picker">
          Список
          <select
            value={listId}
            disabled={working}
            onChange={(event) => {
              setListId(event.target.value);
              setSelectedTags([]);
              setDraft("");
              setNotice("");
              setError("");
            }}
          >
            {me.shopping_lists.map((list) => (
              <option key={list.id} value={list.id}>
                {list.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="app-summary">
        <span>
          {pending.length} к покупке · {completed.length} куплено
        </span>
        <span className="app-sync">
          <i className={connected ? "online" : ""} />
          {connected ? "Обновляется вживую" : "Соединяемся…"}
        </span>
      </div>
      {!!(tags.length || selectedTags.length) && (
        <nav className="app-filters" aria-label="Фильтр по тегам">
          <button
            aria-pressed={!selectedTags.length}
            onClick={() => setSelectedTags([])}
          >
            Все
          </button>
          {tags.map((tag) => (
            <button
              key={tag.id}
              aria-pressed={selectedTags.includes(tag.name)}
              onClick={() =>
                setSelectedTags((current) =>
                  current.includes(tag.name)
                    ? current.filter((name) => name !== tag.name)
                    : [...current, tag.name],
                )
              }
            >
              {tag.name}
            </button>
          ))}
        </nav>
      )}
      <div className="app-feedback" aria-live="polite">
        {notice}
      </div>
      {(error || itemsQuery.isError) && (
        <p role="alert" className="app-error">
          {error || errorMessage(itemsQuery.error)}
        </p>
      )}
      {!listId ? (
        <div className="app-empty">
          <h2>Пока нет доступного списка</h2>
          <p>Попросите администратора предоставить доступ.</p>
        </div>
      ) : itemsQuery.isPending ? (
        <p className="app-empty" role="status">
          Загружаем покупки…
        </p>
      ) : (
        !itemsQuery.isError && (
          <>
            {!!pending.length && (
              <ul className="app-items">{pending.map(row)}</ul>
            )}
            {!pending.length && (
              <div className="app-empty">
                <span aria-hidden="true">✓</span>
                <h2>
                  {selectedTags.length
                    ? "Здесь больше нет покупок"
                    : totalCompleted
                      ? "Всё куплено"
                      : "Начнём со списка"}
                </h2>
                <p>
                  {selectedTags.length
                    ? "Выберите другие теги или добавьте покупку."
                    : "Добавьте первую покупку в поле внизу."}
                </p>
              </div>
            )}
            {!!completed.length && (
              <details className="app-completed">
                <summary>
                  Куплено <span>{completed.length}</span>
                </summary>
                <ul className="app-items">{completed.map(row)}</ul>
              </details>
            )}
            {!!totalCompleted && (
              <button
                className="app-clear"
                disabled={working}
                onClick={() => {
                  if (
                    confirm(
                      `Удалить все купленные позиции из списка (${totalCompleted})?`,
                    )
                  )
                    void action(
                      () =>
                        clear.mutateAsync({
                          params: { header: deviceHeaders },
                          body: { shopping_list_id: listId },
                        }),
                      () => setNotice("Купленные позиции удалены"),
                    );
                }}
              >
                Очистить всё купленное · {totalCompleted}
              </button>
            )}
          </>
        )
      )}
      {!!listId && (
        <form
          className="app-add"
          onSubmit={(event) => {
            event.preventDefault();
            if (!draft.trim()) return;
            void action(async () => {
              const result = await add.mutateAsync({
                params: { header: deviceHeaders },
                body: {
                  shopping_list_id: listId,
                  text: draft.trim(),
                  tags: selectedTags,
                },
              });
              setNotice(
                result.result.status === "merged"
                  ? `Объединено: ${result.result.item.name}`
                  : `Добавлено: ${result.result.item.name}`,
              );
              setDraft("");
              input.current?.focus();
            });
          }}
        >
          <div className="app-add-field">
            <label htmlFor="quick-add">
              Добавить покупку
              {selectedTags.length ? ` · ${selectedTags.join(", ")}` : ""}
            </label>
            <input
              id="quick-add"
              ref={input}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              readOnly={working}
              placeholder="Например, молоко 2 л"
              autoComplete="off"
              enterKeyHint="done"
              required
            />
          </div>
          <button
            className="app-primary"
            disabled={working || !draft.trim()}
            aria-label="Добавить покупку"
          >
            {add.isPending ? "…" : "+"}
          </button>
        </form>
      )}
    </div>
  );
}

export function App() {
  const cache = useQueryClient();
  const me = $api.useQuery("get", "/api/me");
  const [signedOut, setSignedOut] = useState(false);
  function onLogout() {
    cache.clear();
    setSignedOut(true);
  }
  if (me.isPending && !signedOut)
    return (
      <div className="app-login">
        <Brand />
        <p role="status">Загружаем…</p>
      </div>
    );
  if (me.data && !signedOut)
    return <Shopping me={me.data} onLogout={onLogout} />;
  if (me.isError && !isUnauthenticated(me.error) && !signedOut)
    return (
      <div className="app-login">
        <Brand />
        <p role="alert" className="app-error">
          {errorMessage(me.error)}
        </p>
        <button onClick={() => void me.refetch()}>Повторить</button>
      </div>
    );
  return (
    <Login
      onLogin={(user) => {
        const consentId = new URLSearchParams(location.search).get("consent");
        if (consentId && /^[0-9a-f-]{36}$/i.test(consentId)) {
          location.assign(`/consent?request=${encodeURIComponent(consentId)}`);
          return;
        }
        cache.setQueryData(["get", "/api/me"], user);
        setSignedOut(false);
      }}
    />
  );
}

if (
  document.getElementById("app-root") &&
  location.pathname.replace(/\/$/, "") !== "/consent"
) {
  document.getElementById("landing")!.hidden = true;
  document.title = "Покупки — GroceryList";
  createRoot(document.getElementById("app-root")!).render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}
