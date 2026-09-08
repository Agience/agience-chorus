#!/usr/bin/env node
// Vendor the cross-repo BUILD inputs into ./vendor, so the standalone facet build is
// self-contained. Run before `npm run build` or `docker build` (the sibling repo is NOT in the
// Docker context):
//
//   node scripts/vendor-build-inputs.mjs [path-to-types-owner]   # default ../../../../agience-crystal
//
// Only the content-type primitives + `build_info.json` are needed at build time — chorus persona
// types/viewers are fetched at RUNTIME.
//
// ⛔ THE DEFAULT WAS `../agience-core`, A REPO THAT DOES NOT EXIST [corrected 2026-08-04]. It was
// the pre-rename name, and the definitions did not follow the rename into agience-beam — they now
// live in **agience-crystal**, which owns content-type registration (`crystal.type_registration`).
// MEASURED: `agience-crystal/src/types` is the same tree as the committed `vendor/package/types`
// snapshot plus two definitions the snapshot lacks (vnd.agience.issuer+json, vnd.agience.secret+json).
// ⬆ RE-MEASURED 2026-08-25: that gap is CLOSED. Both trees are 59 files and, at HEAD, 58 of
// 59 are byte-identical - only this vendor tree's own README.md differs, which is correct since
// it documents the layout rather than mirroring crystal's. The snapshot has caught up.
// ⚠ What still has no check is STALENESS: the Dockerfile guard asserts the directory EXISTS,
// not that it MATCHES its owner. Edit `agience-crystal/src/types` without re-running this and
// the browser bundle keeps serving the old definitions with nothing red.
//
// ⚠ TWO LAYOUTS, BECAUSE THE OWNER MOVED AND THE VENDORED PATH DID NOT. The vendor DESTINATION
// stays `vendor/package/types` — vite.config.ts and the Dockerfile guard both name it, and
// renaming it here would be a third place to keep in step for no gain. Only the SOURCE is
// resolved flexibly, so pointing this at crystal (src/types) or at any future owner that keeps the
// old package/types shape both work.
import { cpSync, mkdirSync, existsSync, copyFileSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const here = dirname(fileURLToPath(import.meta.url))
const facetRoot = resolve(here, '..')
// facetRoot = <workspace>/agience-chorus/src/astra/web -> four up is the workspace root.
const owner = resolve(process.argv[2] || process.env.AGIENCE_TYPES_REPO || process.env.AGIENCE_CORE
  || resolve(facetRoot, '../../../../agience-crystal'))

const typesCandidates = [resolve(owner, 'src/types'), resolve(owner, 'package/types')]
const typesSrc = typesCandidates.find(existsSync)
const buildInfoSrc = resolve(owner, 'build_info.json')
const vendor = resolve(facetRoot, 'vendor')

if (!typesSrc) {
  console.error(`vendor-build-inputs: no content-type tree under ${owner}`)
  console.error(`  looked for: ${typesCandidates.join('\n              ')}`)
  console.error('Pass the owning checkout path as arg 1 (or set AGIENCE_TYPES_REPO).')
  process.exit(1)
}

const typesDest = resolve(vendor, 'package/types')
rmSync(typesDest, { recursive: true, force: true })
mkdirSync(dirname(typesDest), { recursive: true })
cpSync(typesSrc, typesDest, { recursive: true })

// build_info.json is OPTIONAL and its absence is REPORTED, not passed over. agience-crystal does
// not carry one, so the committed vendor/build_info.json is left in place rather than refreshed —
// say that out loud, because a silent no-op here reads identically to a successful copy and would
// let a stale version string ship as if it had just been stamped.
let bi = ''
if (existsSync(buildInfoSrc)) {
  copyFileSync(buildInfoSrc, resolve(vendor, 'build_info.json'))
  bi = ' + build_info.json'
} else {
  bi = ` (build_info.json NOT refreshed: none at ${buildInfoSrc}; existing vendor copy kept)`
}
console.log(`vendor-build-inputs: vendored ${typesSrc} -> ${typesDest}${bi}`)
