/* The full-video upgrade follows stored ancestry, never guessed media URLs. */
export function requestedRangeDuration(selected) {
  if (!("start" in selected) || !("end" in selected)) return null;
  if (!Number.isFinite(selected.start) || !Number.isFinite(selected.end)) return NaN;
  // Subtract the serialized decimal seconds, as the API does. Binary float
  // subtraction would turn 0.3 - 0.1 into a max below the valid endpoint 0.2.
  const decimal = value => {
    const [coefficient, exponent = "0"] = String(value).split("e");
    const [integer, fraction = ""] = coefficient.split(".");
    return { units: BigInt(integer + fraction), scale: fraction.length - Number(exponent) };
  };
  const start = decimal(selected.start), end = decimal(selected.end), scale = Math.max(start.scale, end.scale);
  const units = end.units * 10n ** BigInt(scale - end.scale) - start.units * 10n ** BigInt(scale - start.scale);
  return Number(`${units}e${-scale}`);
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
