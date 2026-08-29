import {test} from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const source=fs.readFileSync(new URL('../src/views/PromptManageView.vue',import.meta.url),'utf8')

test('prompt history renders only the canonical active version as enabled',()=>{
  assert.match(source,/function isCanonicalActiveTemplate/)
  assert.match(source,/v-if="isCanonicalActiveTemplate\(item\)" class="badge bg-success">启用中/)
  assert.doesNotMatch(source,/v-if="item\.is_active" class="badge bg-success">启用中/)
})
