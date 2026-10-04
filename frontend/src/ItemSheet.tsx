import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  $api,
  deviceHeaders,
  errorMessage,
  isUnauthenticated,
} from "./api/client.js";
import type { components } from "./api/schema.js";
import "./styles/item-sheet.css";

type Item = components["schemas"]["ItemRead"];
type Patch = components["schemas"]["ItemUpdate"];
const units = ["шт", "г", "кг", "мл", "л", "уп"];
const clean = (value: string) => value.trim().replace(/\s+/g, " ");
const tagKey = (value: string) => clean(value).toLowerCase().replace(/ё/g, "е");
const tagSet = (values: string[]) =>
  [...new Set(values.map(tagKey))].sort().join("\n");

export function ItemSheet({
  item,
  current,
  onClose,
  onSaved,
  onLogout,
}: {
  item: Item;
  current: Item | undefined;
  onClose: () => void;
  onSaved: (message: string) => void;
  onLogout: () => void;
}) {
  const cache = useQueryClient();
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const lock = useRef(false);
  const [name, setName] = useState(item.name);
  const [quantity, setQuantity] = useState(
    item.quantity === null ? "" : String(item.quantity),
  );
  const [unit, setUnit] = useState(
    item.unit === null ? "" : units.includes(item.unit) ? item.unit : "custom",
  );
  const [customUnit, setCustomUnit] = useState(
    item.unit && !units.includes(item.unit) ? item.unit : "",
  );
  const [tags, setTags] = useState(item.tags.map((tag) => tag.name));
  const [tagDraft, setTagDraft] = useState("");
  const [note, setNote] = useState(item.note ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const update = $api.useMutation("patch", "/api/items/{id}");
  const remove = $api.useMutation("delete", "/api/items/{id}");
  const tagQuery = $api.useQuery("get", "/api/tags", {
    params: { query: { shopping_list_id: item.shopping_list_id } },
  });
  const initialQuantity = item.quantity === null ? "" : String(item.quantity);
  const chosenUnit = unit === "custom" ? clean(customUnit) : unit;
  const dirty =
    name !== item.name ||
    quantity !== initialQuantity ||
    chosenUnit !== (item.unit ?? "") ||
    tagSet(tags) !== tagSet(item.tags.map((tag) => tag.name)) ||
    !!tagDraft.trim() ||
    note !== (item.note ?? "");
  const deleted = current === undefined;

  useEffect(() => {
    const element = dialog.current!;
    const previous = document.activeElement;
    element.showModal();
    heading.current?.focus();
    document.body.classList.add("item-sheet-open");
    return () => {
      element.close();
      document.body.classList.remove("item-sheet-open");
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, []);

  function close() {
    if (lock.current) return;
    if (!dirty || confirm("Закрыть карточку без сохранения изменений?"))
      onClose();
  }

  function includeTag(value: string, source = tags): string[] {
    const display = clean(value);
    if (!display || source.some((tag) => tagKey(tag) === tagKey(display)))
      return source;
    return [...source, display];
  }

  function addTag(value: string) {
    setTags((previous) => includeTag(value, previous));
    setTagDraft("");
  }

  async function commit(run: () => Promise<unknown>, message: string) {
    if (lock.current || deleted) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await run();
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["get", "/api/items"] }),
        cache.invalidateQueries({ queryKey: ["get", "/api/tags"] }),
      ]);
      onSaved(message);
    } catch (reason) {
      if (isUnauthenticated(reason)) onLogout();
      else setError(errorMessage(reason));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  function save() {
    if (lock.current || deleted) return;
    setError("");
    if (!clean(name)) {
      setError("Введите название покупки");
      return;
    }
    if (unit === "custom" && !chosenUnit) {
      setError("Введите свою единицу или выберите «Без единицы»");
      return;
    }
    const patch: Patch = {};
    if (clean(name) !== item.name) patch.name = clean(name);
    if (quantity !== initialQuantity || chosenUnit !== (item.unit ?? "")) {
      const value = quantity.trim().replace(",", ".");
      if (
        value &&
        (!/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) ||
          !Number.isFinite(Number(value)) ||
          Number(value) <= 0)
      ) {
        setError(
          "Количество должно быть больше нуля, например 1,5. Или оставьте поле пустым.",
        );
        return;
      }
      // The API normalizes the pair together (e.g. 1.5 kg -> 1500 g).
      patch.quantity = value || null;
      patch.unit = chosenUnit || null;
    }
    const finalTags = includeTag(tagDraft);
    if (tagSet(finalTags) !== tagSet(item.tags.map((tag) => tag.name)))
      patch.tags = finalTags;
    if (note !== (item.note ?? "")) patch.note = note.trim() ? note : null;
    if (!Object.keys(patch).length) {
      onClose();
      return;
    }
    void commit(
      () =>
        update.mutateAsync({
          params: { header: deviceHeaders, path: { id: item.id } },
          body: patch,
        }),
      "Покупка сохранена",
    );
  }

  const suggestions = (tagQuery.data ?? [])
    .filter(
      (tag) =>
        !tags.some((selected) => tagKey(selected) === tagKey(tag.name)) &&
        tagKey(tag.name).includes(tagKey(tagDraft)),
    )
    .slice(0, 8);
  return (
    <dialog
      ref={dialog}
      className="item-sheet"
      aria-labelledby="item-sheet-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom
        )
          close();
      }}
    >
      <div className="item-sheet-handle" aria-hidden="true" />
      <header className="item-sheet-header">
        <h2 id="item-sheet-title" ref={heading} tabIndex={-1}>
          Карточка покупки
        </h2>
        <button
          type="button"
          className="item-sheet-close"
          aria-label="Закрыть карточку"
          disabled={busy}
          onClick={close}
        >
          ×
        </button>
      </header>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <div className="item-sheet-body">
          {deleted && (
            <p role="alert" className="app-error">
              Позиция уже удалена. Закройте карточку, чтобы вернуться к списку.
            </p>
          )}
          {!deleted && current.updated_at !== item.updated_at && !busy && (
            <p className="app-muted app-small" role="status">
              Позиция обновилась в другой вкладке или у ассистента. При
              сохранении будут записаны только изменённые вами поля.
            </p>
          )}
          {error && (
            <p role="alert" className="app-error">
              {error}
            </p>
          )}
          <fieldset disabled={busy || deleted}>
            <label>
              Название
              <input
                name="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={255}
                required
              />
            </label>
            <div className="item-sheet-amount">
              <label>
                Количество
                <input
                  name="quantity"
                  inputMode="decimal"
                  value={quantity}
                  onChange={(event) => setQuantity(event.target.value)}
                  placeholder="Не указано"
                  aria-describedby="quantity-hint"
                />
              </label>
              <label>
                Единица
                <select
                  value={unit}
                  onChange={(event) => setUnit(event.target.value)}
                >
                  <option value="">Без единицы</option>
                  {units.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                  <option value="custom">Своя…</option>
                </select>
              </label>
            </div>
            {unit === "custom" && (
              <label>
                Своя единица
                <input
                  value={customUnit}
                  onChange={(event) => setCustomUnit(event.target.value)}
                  maxLength={64}
                  placeholder="Например, бутылка"
                  required
                />
              </label>
            )}
            <p id="quantity-hint" className="app-muted app-small">
              Количество можно оставить пустым.
            </p>
            <div className="item-sheet-tags">
              <label htmlFor="item-tag">Теги</label>
              {!!tags.length && (
                <div className="item-sheet-chips">
                  {tags.map((tag) => (
                    <button
                      type="button"
                      key={tagKey(tag)}
                      onClick={() =>
                        setTags((previous) =>
                          previous.filter(
                            (value) => tagKey(value) !== tagKey(tag),
                          ),
                        )
                      }
                      aria-label={`Убрать тег «${tag}»`}
                    >
                      {tag}
                      <span aria-hidden="true"> ×</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="item-sheet-tag-entry">
                <input
                  id="item-tag"
                  value={tagDraft}
                  maxLength={255}
                  autoComplete="off"
                  placeholder="Выберите или введите тег"
                  onChange={(event) => setTagDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (
                      event.key === "Enter" &&
                      !event.nativeEvent.isComposing
                    ) {
                      event.preventDefault();
                      addTag(tagDraft);
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={() => addTag(tagDraft)}
                  disabled={!tagDraft.trim()}
                >
                  Добавить тег
                </button>
              </div>
              {!!suggestions.length && (
                <div
                  className="item-sheet-suggestions"
                  role="group"
                  aria-label="Подсказки тегов"
                >
                  {suggestions.map((tag) => (
                    <button
                      key={tag.id}
                      type="button"
                      onClick={() => addTag(tag.name)}
                    >
                      {tag.name}
                    </button>
                  ))}
                </div>
              )}
              {tagQuery.isError && (
                <p className="app-muted app-small">
                  Не удалось загрузить подсказки. Тег можно ввести вручную.
                </p>
              )}
            </div>
            <label>
              Заметка
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                placeholder="Марка, вкус или другие подробности"
              />
            </label>
          </fieldset>
        </div>
        <footer className="item-sheet-footer">
          <button
            type="button"
            className="item-sheet-delete"
            disabled={busy || deleted}
            onClick={() => {
              if (confirm(`Удалить «${item.name}» из списка?`))
                void commit(
                  () =>
                    remove.mutateAsync({
                      params: { header: deviceHeaders, path: { id: item.id } },
                    }),
                  "Покупка удалена",
                );
            }}
          >
            {remove.isPending ? "Удаляем…" : "Удалить покупку"}
          </button>
          <button
            type="submit"
            className="app-primary"
            disabled={busy || deleted}
          >
            {update.isPending ? "Сохраняем…" : "Сохранить"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
