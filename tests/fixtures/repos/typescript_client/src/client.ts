import { fetchOrder } from "./api";

export function loadOrder(id: string) {
  return fetchOrder(id);
}
