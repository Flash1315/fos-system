import { Alert } from "react-native";
import { shouldSkipErrorAlert } from "./api";

/** Show Fos error alert unless session was already cleared (App shows that dialog). */
export function alertFosError(err: unknown, fallback = "Failed"): void {
  if (shouldSkipErrorAlert(err)) return;
  Alert.alert("Fos", err instanceof Error ? err.message : fallback);
}
