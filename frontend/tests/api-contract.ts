import type { components, paths } from "../src/api/schema.js";

declare const item: components["schemas"]["ItemRead"];
const quantity: number | null = item.quantity;
// @ts-expect-error quantity сериализуется числом, не строкой
const wrongQuantity: string = item.quantity;

declare const event: components["schemas"]["ShoppingListEventRead"];
if (event.type === "items_added") {
  const results: components["schemas"]["ItemsAddedPayload"]["results"] = event.payload.results;
  const type: "items_added" = event.type;
  const added: components["schemas"]["ItemsAddedEvent"] = event;
  void results;
  void type;
  void added;
}

declare const response: paths["/api/items"]["get"]["responses"][200]["content"]["application/json"];
const items: components["schemas"]["ItemRead"][] = response;
void quantity;
void wrongQuantity;
void items;

if (event.type === "tags_merged") {
  const tag: components["schemas"]["TagRead"] = event.payload.tag;
  const previousTag: components["schemas"]["TagRead"] = event.payload.previous_tag;
  void tag;
  void previousTag;
}
