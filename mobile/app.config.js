const app = require("./app.json");

/**
 * Production EAS sets EXPO_PUBLIC_APP_ENV=production.
 * Require a real https API URL via eas.json env or EAS secrets.
 */
module.exports = () => {
  const expo = app.expo;
  const appEnv = (process.env.EXPO_PUBLIC_APP_ENV || "").trim().toLowerCase();
  const apiUrl = (process.env.EXPO_PUBLIC_API_URL || "").trim();
  if (appEnv === "production") {
    if (!apiUrl) {
      throw new Error(
        "EXPO_PUBLIC_API_URL is required for production builds (set in EAS secrets or eas.json env)",
      );
    }
    if (!/^https:\/\//i.test(apiUrl)) {
      throw new Error("EXPO_PUBLIC_API_URL must use https:// for production builds");
    }
  }
  return expo;
};
