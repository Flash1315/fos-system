# Fos EAS production builds

In-repo readiness for Expo Application Services. Store submit still needs your Expo/Apple/Google credentials.

## Prerequisites

1. Expo account + `npm i -g eas-cli` (or `npx eas-cli`)
2. From `mobile/`: `eas login` then `eas init` (writes `extra.eas.projectId` into the Expo config)
3. Set EAS secret for the production API:

```bash
eas secret:create --scope project --name EXPO_PUBLIC_API_URL --value https://api.your-domain.com
```

`app.config.js` **fails the build** when `EXPO_PUBLIC_APP_ENV=production` and `EXPO_PUBLIC_API_URL` is missing or not `https://`.

## Profiles (`eas.json`)

| Profile | Purpose |
|---------|---------|
| `development` | Dev client |
| `preview` | Internal distribution; requires https API URL when `EXPO_PUBLIC_APP_ENV=preview` |
| `production` | Store-oriented; `autoIncrement`; `EXPO_PUBLIC_APP_ENV=production` |

## Commands

```bash
cd mobile
npm run config:check          # local expo config
npm run config:check:prod     # asserts production env gate
eas build --profile preview --platform android
eas build --profile production --platform all
# submit when credentials exist:
# eas submit --profile production --platform ios
```

## Versioning

- Keep `mobile/app.json` / `package.json` version in sync with API `APP_VERSION`
- Production uses `cli.appVersionSource: remote` — Expo dashboard owns store build numbers after first link
- Bundle IDs: iOS/Android `app.fos.system`

## CI

GitHub Actions runs `expo config` with a dummy https URL (and a negative check without URL). It does **not** publish to stores.
