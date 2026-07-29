import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";
import AsyncStorage from "@react-native-async-storage/async-storage";

/** Device-bound keychain options (iOS); ignored on Android/web. */
const secureOpts: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

/** SecureStore on device; AsyncStorage fallback for web/dev. */
export async function storageGet(key: string) {
  if (Platform.OS === "web") return AsyncStorage.getItem(key);
  return SecureStore.getItemAsync(key, secureOpts);
}

export async function storageSet(key: string, value: string) {
  if (Platform.OS === "web") return AsyncStorage.setItem(key, value);
  return SecureStore.setItemAsync(key, value, secureOpts);
}

export async function storageDelete(key: string) {
  if (Platform.OS === "web") return AsyncStorage.removeItem(key);
  return SecureStore.deleteItemAsync(key, secureOpts);
}

/** Non-sensitive, potentially larger values such as form drafts. */
export function asyncStorageGet(key: string) {
  return AsyncStorage.getItem(key);
}

export function asyncStorageSet(key: string, value: string) {
  return AsyncStorage.setItem(key, value);
}

export function asyncStorageDelete(key: string) {
  return AsyncStorage.removeItem(key);
}
