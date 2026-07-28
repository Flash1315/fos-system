const app = require("./app.json");

/**
 * EAS profiles set EXPO_PUBLIC_APP_ENV.
 * preview + production require https EXPO_PUBLIC_API_URL (EAS secret or env).
 */
module.exports = () => {
  const expo = { ...app.expo };
  const appEnv = (process.env.EXPO_PUBLIC_APP_ENV || "").trim().toLowerCase();
  const apiUrl = (process.env.EXPO_PUBLIC_API_URL || "").trim().replace(/\/+$/, "");
  const gated = appEnv === "production" || appEnv === "preview";
  if (gated) {
    if (!apiUrl) {
      throw new Error(
        "EXPO_PUBLIC_API_URL is required for preview/production builds (set via EAS secrets or eas.json env)",
      );
    }
    if (!/^https:\/\//i.test(apiUrl)) {
      throw new Error("EXPO_PUBLIC_API_URL must use https:// for preview/production builds");
    }
  }
  expo.extra = {
    ...(expo.extra || {}),
    appEnv: appEnv || "development",
    apiUrl: apiUrl || null,
    eas: {
      ...((expo.extra && expo.extra.eas) || {}),
      // Filled by `eas init` / Expo dashboard; keep placeholder shape for tooling.
      projectId: (expo.extra && expo.extra.eas && expo.extra.eas.projectId) || undefined,
    },
  };
  return expo;
};
