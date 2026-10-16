/* The full-video upgrade follows stored ancestry, never guessed media URLs. */
function serializedSeconds(left, right, subtract = false) {
  if (!Number.isFinite(left) || !Number.isFinite(right)) return NaN;
  // Match serialized decimal seconds, rather than expanding a valid endpoint
  // into binary float error or accepting the next representable value past it.
  const decimal = value => {
    const [coefficient, exponent = "0"] = String(value).split("e");
    const [integer, fraction = ""] = coefficient.split(".");
    return { units: BigInt(integer + fraction), scale: fraction.length - Number(exponent) };
  };
  const a = decimal(left), b = decimal(right), scale = Math.max(a.scale, b.scale);
  const units = a.units * 10n ** BigInt(scale - a.scale) + (subtract ? -1n : 1n) * b.units * 10n ** BigInt(scale - b.scale);
  return Number(`${units}e${-scale}`);
}

export function requestedRangeDuration(selected) {
  if (!("start" in selected) || !("end" in selected)) return null;
  return serializedSeconds(selected.end, selected.start, true);
}

export function absoluteRangeTime(start, seconds) {
  return serializedSeconds(start, seconds);
}

export async function fullVideoSource(taskId, readTask) {
  const visited = new Set();
  let id = taskId;
  for (let depth = 0; depth < 64; depth++) {
    if (visited.has(id)) throw new Error("片段来源关系循环，未猜测原视频。");
    visited.add(id);
    const value = await readTask(id), task = value.task || value;
    if (!task || task.id !== id) throw new Error("原视频身份不匹配，未提交任务。");
    if (!Object.keys(task.learning_range || {}).length) return task;
    if (!task.source_task_id) throw new Error("没有保留完整原视频；请重新导入全片。");
    id = task.source_task_id;
  }
  throw new Error("片段来源链过长，请从资料库打开原视频。");
}
