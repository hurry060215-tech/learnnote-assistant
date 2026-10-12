import assert from "node:assert/strict";
import test from "node:test";
import { createAssistantConversations } from "../assistant-session.js";

test("current topic survives panel toggles but cannot inherit another source or browser load", () => {
  let counter = 0;
  const factory = () => `session-${++counter}`;
  const topics = createAssistantConversations(factory);
  const global = topics.id("global");
  assert.equal(topics.id("global"), global);
  const note = topics.id("task:a");
  assert.notEqual(note, global);
  assert.notEqual(topics.id("material:a"), note);
  assert.notEqual(createAssistantConversations(factory).id("global"), global);
  assert.notEqual(topics.reset("global"), global);
  assert.equal(topics.id("task:a"), note);
});

test("old source contexts are bounded without touching saved drafts or archive", () => {
  let counter = 0;
  const topics = createAssistantConversations(() => `session-${++counter}`);
  const oldest = topics.id("task:0");
  for (let i = 1; i <= 30; i++) topics.id(`task:${i}`);
  assert.notEqual(topics.id("task:0"), oldest);
});
