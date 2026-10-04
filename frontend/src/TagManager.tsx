import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  $api,
  deviceHeaders,
  errorMessage,
  isUnauthenticated,
} from "./api/client.js";
import type { components } from "./api/schema.js";
import "./styles/tags.css";

type Tag = components["schemas"]["TagUsageRead"];
const clean = (name: string) => name.trim().replace(/\s+/g, " ");
const key = (name: string) => clean(name).toLowerCase().replace(/ё/g, "е");

export function TagManager({
  listId,
  listName,
  onBack,
  onLogout,
}: {
  listId: string;
  listName: string;
  onBack: () => void;
  onLogout: () => void;
}) {
  const cache = useQueryClient();
  const tags = $api.useQuery("get", "/api/tags", {
    params: { query: { shopping_list_id: listId } },
  });
  const rename = $api.useMutation("patch", "/api/tags/{id}");
  const create = $api.useMutation("post", "/api/tags");
  const remove = $api.useMutation("delete", "/api/tags/{id}");
  const bulk = $api.useMutation("post", "/api/tags/{id}/bulk");
  const [editing, setEditing] = useState<{
    id: string;
    name: string;
    draft: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [newName, setNewName] = useState("");
  const createInput = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  useEffect(() => {
    if (editing) nameInput.current?.focus();
  }, [editing?.id]);
  useEffect(() => {
    if (isUnauthenticated(tags.error)) onLogout();
  }, [tags.error, onLogout]);
  const missing =
    !!editing && !!tags.data && !tags.data.some((tag) => tag.id === editing.id);

  function discard() {
    return (
      !editing ||
      editing.draft === editing.name ||
      confirm("Отменить переименование без сохранения?")
    );
  }
  async function action(run: () => Promise<string>, finish?: () => void) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const message = await run();
      finish?.();
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["get", "/api/items"] }),
        cache.invalidateQueries({ queryKey: ["get", "/api/tags"] }),
      ]);
      setNotice(message);
    } catch (reason) {
      if (isUnauthenticated(reason)) onLogout();
      else setError(errorMessage(reason));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  function save() {
    if (!editing || missing || lock.current) return;
    const name = clean(editing.draft);
    if (!name) {
      setError("Введите название тега");
      return;
    }
    const target = tags.data?.find(
      (tag) => tag.id !== editing.id && key(tag.name) === key(name),
    );
    if (
      target &&
      !confirm(
        `Объединить «${editing.name}» с «${target.name}»? Все покупки получат тег «${target.name}», а тег «${editing.name}» будет удалён.`,
      )
    )
      return;
    void action(
      async () => {
        const result = await rename.mutateAsync({
          params: { path: { id: editing.id }, header: deviceHeaders },
          body: { name },
        });
        return result.id === editing.id
          ? `Тег переименован: ${result.name}`
          : `Теги объединены: ${result.name}`;
      },
      () => setEditing(null),
    );
  }
  function bulkAction(tag: Tag, kind: "mark_bought" | "delete_items") {
    const question =
      kind === "mark_bought"
        ? `Отметить все покупки с тегом «${tag.name}» купленными? Это изменит их во всех группах.`
        : `Удалить все покупки с тегом «${tag.name}», включая купленные? Они исчезнут из списка и из других групп. Отменить удаление нельзя.`;
    if (!confirm(question)) return;
    void action(async () => {
      const result = await bulk.mutateAsync({
        params: { path: { id: tag.id }, header: deviceHeaders },
        body: { action: kind },
      });
      return kind === "mark_bought"
        ? `Покупки с тегом «${tag.name}» отмечены купленными`
        : `Удалено покупок: ${result.count}`;
    });
  }
  return (
    <div className="app-shell app-tags-page">
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          if (
            discard() &&
            (!newName.trim() ||
              confirm("Закрыть раздел без создания нового тега?"))
          )
            onBack();
        }}
      >
        ← К списку
      </button>
      <div className="app-heading">
        <div>
          <p className="app-eyebrow">{listName}</p>
          <h1 ref={heading} tabIndex={-1}>
            Теги
          </h1>
        </div>
        <button
          className="app-refresh"
          disabled={busy || tags.isFetching}
          onClick={() => void tags.refetch()}
        >
          Обновить
        </button>
      </div>
      <p className="app-muted">
        Создавайте теги заранее или назначайте новые в карточках покупок.
        Счётчик показывает, сколько ещё нужно купить.
      </p>
      <form
        className="app-tag-editor"
        onSubmit={(event) => {
          event.preventDefault();
          const name = clean(newName);
          if (!name || editing) return;
          void action(
            async () => {
              const result = await create.mutateAsync({
                params: { header: deviceHeaders },
                body: { shopping_list_id: listId, name },
              });
              return `Тег создан: ${result.name}`;
            },
            () => {
              setNewName("");
              createInput.current?.focus();
            },
          );
        }}
      >
        <label htmlFor="new-tag-name">Новый тег</label>
        <input
          id="new-tag-name"
          ref={createInput}
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
          placeholder="Например, На неделю"
          maxLength={255}
          required
          readOnly={busy}
          disabled={!!editing}
          autoComplete="off"
        />
        <div className="app-tag-actions">
          <button
            type="submit"
            className="app-primary"
            disabled={busy || !!editing || !clean(newName)}
          >
            Создать тег
          </button>
        </div>
      </form>
      <p className="app-feedback" role="status">
        {busy ? "Сохраняем…" : notice}
      </p>
      {(error || tags.isError) && (
        <p className="app-error" role="alert">
          {error || errorMessage(tags.error)}
        </p>
      )}
      {editing && (
        <form
          className="app-tag-editor"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <label htmlFor="tag-name">Новое название тега «{editing.name}»</label>
          <input
            id="tag-name"
            ref={nameInput}
            value={editing.draft}
            maxLength={255}
            required
            disabled={busy || missing}
            onChange={(event) =>
              setEditing({ ...editing, draft: event.target.value })
            }
          />
          <p className="app-muted app-small">
            Название существующего тега объединит их покупки. Перед объединением
            появится подтверждение.
          </p>
          {missing && (
            <p role="alert" className="app-error">
              Тег удалён или объединён в другой вкладке. Отмените
              переименование.
            </p>
          )}
          <div className="app-tag-actions">
            <button
              type="submit"
              className="app-primary"
              disabled={busy || missing}
            >
              Сохранить название
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (discard()) setEditing(null);
              }}
            >
              Отмена
            </button>
          </div>
        </form>
      )}
      {tags.isPending ? (
        <p role="status">Загружаем теги…</p>
      ) : !tags.isError && !tags.data?.length ? (
        <div className="app-empty">
          <h2>Пока нет тегов</h2>
          <p>Создайте первый тег в форме выше или в карточке покупки.</p>
        </div>
      ) : (
        <ul className="app-tags-list">
          {[...(tags.data ?? [])]
            .sort((a, b) => a.name.localeCompare(b.name, "ru"))
            .map((tag) => (
              <li key={tag.id}>
                <details>
                  <summary>
                    <span>{tag.name}</span>
                    <span className="app-muted app-small">
                      {tag.open_count} к покупке
                    </span>
                  </summary>
                  <div className="app-tag-actions">
                    <button
                      disabled={busy || !!editing}
                      onClick={() => {
                        setError("");
                        setNotice("");
                        setEditing({
                          id: tag.id,
                          name: tag.name,
                          draft: tag.name,
                        });
                      }}
                    >
                      Переименовать
                    </button>
                    <button
                      disabled={busy || !!editing || !tag.open_count}
                      onClick={() => bulkAction(tag, "mark_bought")}
                    >
                      Отметить все купленными
                    </button>
                    <button
                      className="app-tag-danger"
                      disabled={busy || !!editing}
                      onClick={() => bulkAction(tag, "delete_items")}
                    >
                      Удалить все покупки с тегом
                    </button>
                    <button
                      className="app-tag-danger"
                      disabled={busy || !!editing}
                      onClick={() => {
                        if (
                          confirm(
                            `Удалить тег «${tag.name}» со всех покупок? Сами покупки останутся в списке.`,
                          )
                        )
                          void action(async () => {
                            await remove.mutateAsync({
                              params: {
                                path: { id: tag.id },
                                header: deviceHeaders,
                              },
                            });
                            return `Тег «${tag.name}» удалён. Покупки сохранены`;
                          });
                      }}
                    >
                      Удалить только тег
                    </button>
                  </div>
                </details>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
