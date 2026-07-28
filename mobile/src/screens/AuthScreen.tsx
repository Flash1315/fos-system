import React, { useEffect, useState } from "react";
import { Alert } from "react-native";
import { login, registerOrg, type User } from "../api";
import { storageGet, storageSet } from "../storage";
import { Brand, Btn, Card, Field, Label, LinkText, Screen, Sub } from "../components/ui";

const LAST_SLUG_KEY = "fos_last_org_slug";
const LAST_EMAIL_KEY = "fos_last_email";

const DEMO_SLUG =
  (typeof process !== "undefined" && process.env?.EXPO_PUBLIC_DEMO_SLUG) || "demo2092";
const DEMO_EMAIL =
  (typeof process !== "undefined" && process.env?.EXPO_PUBLIC_DEMO_EMAIL) ||
  "owner@demo2092.example.com";
const DEMO_PASSWORD =
  (typeof process !== "undefined" && process.env?.EXPO_PUBLIC_DEMO_PASSWORD) || "secret12";
const DEMO_ENABLED =
  (typeof process !== "undefined" && process.env?.EXPO_PUBLIC_DEMO_LOGIN) === "1";

export function AuthScreen({
  busy,
  setBusy,
  onDone,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  onDone: (token: string, user: User) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [orgSlug, setOrgSlug] = useState("");
  const [orgName, setOrgName] = useState("");
  const [currency, setCurrency] = useState("IDR");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberedSlug, setRememberedSlug] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [slug, mail] = await Promise.all([
          storageGet(LAST_SLUG_KEY),
          storageGet(LAST_EMAIL_KEY),
        ]);
        if (slug) {
          setOrgSlug(slug);
          setRememberedSlug(slug);
        }
        if (mail) setEmail(mail);
      } catch {
        /* ignore */
      }
    })();
  }, []);

  const fillDemo = () => {
    setMode("login");
    setOrgSlug(DEMO_SLUG);
    setEmail(DEMO_EMAIL);
    setPassword(DEMO_PASSWORD);
  };

  const submit = async () => {
    if (!orgSlug.trim()) {
      Alert.alert("Fos", "Organization slug is required");
      return;
    }
    if (!email.trim() || !password) {
      Alert.alert("Fos", "Email and password are required");
      return;
    }
    if (password.length < 6) {
      Alert.alert("Fos", "Password must be at least 6 characters");
      return;
    }
    if (mode === "register") {
      if (!orgName.trim() || orgName.trim().length < 2) {
        Alert.alert("Fos", "Company name must be at least 2 characters");
        return;
      }
      if (!name.trim() || name.trim().length < 2) {
        Alert.alert("Fos", "Your name must be at least 2 characters");
        return;
      }
      if (!/^[a-z0-9-]+$/.test(orgSlug.toLowerCase().trim())) {
        Alert.alert("Fos", "Slug: lowercase letters, numbers, hyphens only");
        return;
      }
    }
    const slug = orgSlug.toLowerCase().trim();
    const mail = email.trim();
    setBusy(true);
    try {
      if (mode === "register") {
        const res = await registerOrg({
          name: orgName.trim(),
          slug,
          currency: currency.trim().toUpperCase() || "IDR",
          owner_email: mail,
          owner_name: name.trim(),
          owner_password: password,
        });
        await storageSet(LAST_SLUG_KEY, slug);
        await storageSet(LAST_EMAIL_KEY, mail);
        setRememberedSlug(slug);
        onDone(res.access_token, res.user);
      } else {
        const res = await login({
          email: mail,
          password,
          organization_slug: slug,
        });
        await storageSet(LAST_SLUG_KEY, slug);
        await storageSet(LAST_EMAIL_KEY, mail);
        setRememberedSlug(slug);
        onDone(res.access_token, res.user);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed";
      const friendly =
        /invalid|credential|401|unauthorized/i.test(msg)
          ? "Check company slug, email, and password. Invited teammates use the slug from their manager — not Register."
          : msg;
      Alert.alert("Fos", friendly);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen scroll>
      <Brand />
      <Sub>Field money. Clear books.</Sub>
      <Sub>
        {mode === "login"
          ? "Joining a team? Use the company slug and password from your manager. Register only to create a new company."
          : "Creates your organization and owner account."}
      </Sub>
      {mode === "login" && !!rememberedSlug && (
        <Sub>Remembered company: /{rememberedSlug}</Sub>
      )}
      <Card>
        <Label>Organization slug</Label>
        <Field autoCapitalize="none" value={orgSlug} onChangeText={setOrgSlug} placeholder="my-company" />
        {mode === "register" && (
          <>
            <Label>Company name</Label>
            <Field value={orgName} onChangeText={setOrgName} placeholder="Acme Field Ops" />
            <Label>Currency</Label>
            <Field autoCapitalize="characters" value={currency} onChangeText={setCurrency} placeholder="IDR" />
            <Label>Your name</Label>
            <Field value={name} onChangeText={setName} placeholder="Alex" />
          </>
        )}
        <Label>Email</Label>
        <Field
          autoCapitalize="none"
          keyboardType="email-address"
          value={email}
          onChangeText={setEmail}
          placeholder="you@example.com"
        />
        <Label>Password</Label>
        <Field
          secureTextEntry={!showPassword}
          value={password}
          onChangeText={setPassword}
          placeholder="min 6 characters"
        />
        <LinkText onPress={() => setShowPassword((v) => !v)}>
          {showPassword ? "Hide password" : "Show password"}
        </LinkText>
        <Btn title={busy ? "…" : mode === "login" ? "Log in" : "Create company"} onPress={submit} disabled={busy} />
        {mode === "login" && DEMO_ENABLED && (
          <Btn title="Use demo workspace" variant="ghost" onPress={fillDemo} disabled={busy} />
        )}
      </Card>
      <LinkText onPress={() => setMode(mode === "login" ? "register" : "login")}>
        {mode === "login" ? "New company? Register" : "Have an account? Log in"}
      </LinkText>
    </Screen>
  );
}
