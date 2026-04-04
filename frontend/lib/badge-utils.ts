/**
 * getBadgeStyle — returns Tailwind className string for status/priority badges.
 *
 * Centralizes all status-to-color mappings so badge colors are never
 * defined inline in JSX. Add new statuses here under the appropriate type,
 * not in individual components.
 *
 * To add a new status: add a case under the relevant `type` block with
 * the Tailwind bg + text classes. Use semantic color pairs (e.g. bg-gray-100 text-gray-700).
 *
 * @param type - "ticket_status" | "problem_status" | "priority"
 * @param value - The status or priority string value (case-insensitive)
 * @returns Tailwind className string for the badge (bg + text + padding + rounded)
 */
export function getBadgeStyle(
  type: "ticket_status" | "problem_status" | "priority",
  value: string
): string {
  const v = (value || "").toLowerCase().replace(/_/g, " ");
  const base = "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium";

  if (type === "ticket_status") {
    switch (v) {
      case "open":
        return `${base} bg-gray-100 text-gray-700`;
      case "in progress":
      case "in_progress":
        return `${base} bg-blue-100 text-blue-700`;
      case "pending":
        return `${base} bg-amber-100 text-amber-700`;
      case "resolved":
        return `${base} bg-teal-100 text-teal-700`;
      case "closed":
        return `${base} bg-gray-200 text-gray-500`;
      case "waiting for customer":
      case "waiting_for_customer":
        return `${base} bg-purple-100 text-purple-700`;
      case "waiting for support vendor":
      case "waiting_for_support_vendor":
        return `${base} bg-orange-100 text-orange-700`;
      default:
        return `${base} bg-gray-100 text-gray-600`;
    }
  }

  if (type === "problem_status") {
    switch (v) {
      case "open":
        return `${base} bg-gray-100 text-gray-700`;
      case "investigating":
        return `${base} bg-amber-100 text-amber-700`;
      case "known_error":
      case "known error":
        return `${base} bg-red-100 text-red-700`;
      case "resolved":
        return `${base} bg-teal-100 text-teal-700`;
      case "closed":
        return `${base} bg-gray-200 text-gray-500`;
      default:
        return `${base} bg-gray-100 text-gray-600`;
    }
  }

  if (type === "priority") {
    switch (v) {
      case "critical":
        return `${base} bg-red-100 text-red-700`;
      case "high":
        return `${base} bg-orange-100 text-orange-700`;
      case "medium":
        return `${base} bg-amber-100 text-amber-700`;
      case "low":
        return `${base} bg-gray-100 text-gray-600`;
      default:
        return `${base} bg-gray-100 text-gray-600`;
    }
  }

  return `${base} bg-gray-100 text-gray-600`;
}
