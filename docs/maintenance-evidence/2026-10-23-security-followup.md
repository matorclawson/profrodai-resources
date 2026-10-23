# Locked test-toolchain security follow-up: 2026-10-23

sow: profrod-SOW-338

A fresh PR62 merge onto main abd33c20 found newly reported npm advisories in the existing locked test-toolchain. The retained head-bound gate at 890a3d90 passed the five API tests and stopped at npm audit: one high and two moderate findings. This supersedes the October18 audit observation for the current registry, without rewriting its evidence.

Ran npm audit fix --ignore-scripts --no-fund without --force, within the existing package.json ranges. Only package-lock.json changes; package.json, runtime application source, CI gates and audit thresholds remain unchanged. No package names are added or removed. Updated locked versions:

- node_modules/@oxc-project/types: 0.146.0 -> 0.155.0.
- node_modules/@rolldown/binding-android-arm-eabi: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-android-arm64: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-darwin-arm64: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-darwin-x64: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-freebsd-x64: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-linux-arm-gnueabihf: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-linux-arm64-gnu: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-linux-arm64-musl: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-linux-ppc64-gnu: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-linux-s390x-gnu: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-linux-x64-gnu: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-linux-x64-musl: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-openharmony-arm64: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-win32-arm64-msvc: 1.2.5 -> 1.2.15.
- node_modules/@rolldown/binding-win32-x64-msvc: 1.2.5 -> 1.2.15.
- node_modules/@vitest/expect: 4.1.11 -> 4.1.12.
- node_modules/@vitest/mocker: 4.1.11 -> 4.1.12.
- node_modules/@vitest/pretty-format: 4.1.11 -> 4.1.12.
- node_modules/@vitest/runner: 4.1.11 -> 4.1.12.
- node_modules/@vitest/snapshot: 4.1.11 -> 4.1.12.
- node_modules/@vitest/spy: 4.1.11 -> 4.1.12.
- node_modules/@vitest/utils: 4.1.11 -> 4.1.12.
- node_modules/chai: 6.2.2 -> 6.3.0.
- node_modules/nanoid: 3.3.18 -> 3.3.20.
- node_modules/postcss: 8.5.26 -> 8.5.31.
- node_modules/rolldown: 1.2.5 -> 1.2.15.
- node_modules/tinyrainbow: 3.1.1 -> 3.2.0.
- node_modules/vite: 8.2.2 -> 8.3.5.
- node_modules/vitest: 4.1.11 -> 4.1.12.

The immediate post-update npm audit JSON reports zero vulnerabilities. Full exact-head make verify-pr evidence is retained with the review handoff after this coherent source commit; a zero audit is not notebook end-to-end or paid API verification.

This is a focused npm security follow-up, not a new full weekly npm/PyPI review. The existing maintenance cadence remains last_reviewed2026-10-18, next_due2026-10-25. Both prior review history and the failed 890a3d90 gate remain retained.
