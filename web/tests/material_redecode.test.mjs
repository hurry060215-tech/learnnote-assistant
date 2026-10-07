import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const learning = readFileSync(new URL("../learning.js", import.meta.url), "utf8");
const app = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const library = readFileSync(new URL("../../backend/app/routers/library.py", import.meta.url), "utf8");

assert.match(learning, /material-redecode-panel/);
assert.match(learning, /metadata\.raw_sha256/);
assert.match(learning, /onRedecode\(encoding\.value\)/);
assert.match(app, /\/api\/library\/materials\/\$\{encodeURIComponent\(materialId\)\}\/redecode/);
assert.match(app, /onRedecode: async encoding/);
assert.match(library, /@library_router\.post\("\/materials\/\{material_id\}\/redecode"\)/);
assert.match(library, /redecode_document_material\(material_id, encoding\)/);

console.log("Existing local material can be re-decoded from its preserved source bytes");
