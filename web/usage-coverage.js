// Provider-reported local ledger counts are not an account bill or estimate.
const fields = { input_tokens: "measured_input_requests", output_tokens: "measured_output_requests", total_tokens: "measured_requests" };
const count = value => Number.isSafeInteger(value) && value >= 0;

export function usageCoverage(group, field = "total_tokens") {
  const requests = group?.requests, measured = group?.[fields[field]], value = group?.[field];
  const unknown = { status: "unknown", value: null, text: "未知", detail: "用量覆盖未知" };
  if (!fields[field] || !count(requests)) return unknown;
  if (requests === 0) return { status: "empty", value: 0, text: "0", detail: "尚无请求记录" };
  if (!count(measured) || measured > requests) return unknown;
  const detail = `${measured.toLocaleString()} / ${requests.toLocaleString()} 次有记录`;
  if (measured === 0 || !count(value)) return { ...unknown, detail };
  const partial = measured < requests;
  return { status: partial ? "partial" : "complete", value,
    text: `${partial ? "已记录 " : ""}${value.toLocaleString()}`, detail };
}
