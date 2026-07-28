import React, { useEffect, useRef, useState } from "react";
import { Alert } from "react-native";
import { acceptInvite, login, registerOrg, type User } from "../api";
import { storageDelete, storageGet, storageSet } from "../storage";
import { Brand, Btn, Card, Field, Label, LinkText, Screen, Sub } from "../components/ui";
import { currencyCodeError, emailFormatError, passwordStrengthError } from "../format";

const LAST_SLUG_KEY = "fos_last_org_slug";
const LAST_EMAIL_KEY = "fos_last_email";

const DEMO_SLUG =
  (typeof process !== "undefined" && process.env?.EXPO_PUBLIC_DEMO_SLUG) || "";
const DEMO_EMAIL =
  (typeof process !== "undefined" && process.env?.EXPO_PUBLIC_DEMO_EMAIL) || "";
const DEMO_PASSWORD =
  (typeof process !== "undefined" && process.env?.EXPO_PUBLIC_DEMO_PASSWORD) || "";
const DEMO_ENABLED =
  (typeof process !== "undefined" && process.env?.EXPO_PUBLIC_DEMO_LOGIN) === "1" &&
  !!DEMO_SLUG &&
  !!DEMO_EMAIL &&
  !!DEMO_PASSWORD;

export function AuthScreen({
  busy,
  setBusy,
  onDone,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  onDone: (token: string, user: User, expiresIn?: number) => void | Promise<void>;
}) {
  const [mode, setMode] = useState<"login" | "register" | "invite">("login");
  const [orgSlug, setOrgSlug] = useState("");
  const [orgName, setOrgName] = useState("");
  const [currency, setCurrency] = useState("IDR");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberedSlug, setRememberedSlug] = useState<string | null>(null);
  const [rememberedEmail, setRememberedEmail] = useState<string | null>(null);
  const [formError, setFormError] = useState("");
  const submitLock = useRef(false);

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
        if (mail) {
          setEmail(mail);
          setRememberedEmail(mail);
        }
      } catch {
        /* ignore */
      }
    })();
  }, []);

  const forgetRemembered = async () => {
    try {
      await Promise.all([storageDelete(LAST_SLUG_KEY), storageDelete(LAST_EMAIL_KEY)]);
    } catch {
      /* ignore */
    }
    setRememberedSlug(null);
    setRememberedEmail(null);
    setOrgSlug("");
    setEmail("");
  };

  const fillDemo = () => {
    setMode("login");
    setOrgSlug(DEMO_SLUG);
    setEmail(DEMO_EMAIL);
    setPassword(DEMO_PASSWORD);
  };

  const submit = async () => {
    if (busy || submitLock.current) return;
    setFormError("");
    if (mode === "invite") {
      if (!inviteToken.trim() || inviteToken.trim().length < 16) {
        setFormError("Paste the invite token from your manager");
        return;
      }
      const invitePwErr = passwordStrengthError(password);
      if (invitePwErr) {
        setFormError(invitePwErr);
        return;
      }
      if (password !== passwordConfirm) {
        setFormError("Passwords do not match");
        return;
      }
      submitLock.current = true;
      setBusy(true);
      try {
        const res = await acceptInvite(inviteToken.trim(), password, passwordConfirm);
        if (res.user?.email) {
          await storageSet(LAST_EMAIL_KEY, res.user.email);
        }
        if (res.organization_slug) {
          await storageSet(LAST_SLUG_KEY, res.organization_slug);
          setOrgSlug(res.organization_slug);
          setRememberedSlug(res.organization_slug);
        }
        await onDone(res.access_token, res.user, res.expires_in);
      } catch (e) {
        Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
      } finally {
        submitLock.current = false;
        setBusy(false);
      }
      return;
    }
    if (!orgSlug.trim()) {
      setFormError("Organization slug is required");
      return;
    }
    if (!email.trim() || !password) {
      setFormError("Email and password are required");
      return;
    }
    const mailErr = emailFormatError(email);
    if (mailErr) {
      setFormError(mailErr);
      return;
    }
    if (mode === "register") {
      const regPwErr = passwordStrengthError(password);
      if (regPwErr) {
        setFormError(regPwErr);
        return;
      }
      if (!orgName.trim() || orgName.trim().length < 2) {
        setFormError("Company name must be at least 2 characters");
        return;
      }
      if (!name.trim() || name.trim().length < 2) {
        setFormError("Your name must be at least 2 characters");
        return;
      }
      if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(orgSlug.toLowerCase().trim())) {
        setFormError("Slug: lowercase letters, numbers, hyphens only (no -- or leading/trailing -)");
        return;
      }
      const curErr = currencyCodeError(currency);
      if (curErr) {
        setFormError(curErr);
        return;
      }
      if (password !== passwordConfirm) {
        setFormError("Passwords do not match");
        return;
      }
    } else if (password.length > 128) {
      setFormError("Password is too long (max 128 characters)");
      return;
    }
    const slug = orgSlug.toLowerCase().trim();
    const mail = email.trim().toLowerCase();
    submitLock.current = true;
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
          owner_password_confirm: passwordConfirm,
        });
        await storageSet(LAST_SLUG_KEY, slug);
        await storageSet(LAST_EMAIL_KEY, mail);
        setRememberedSlug(slug);
        await onDone(res.access_token, res.user, res.expires_in);
      } else {
        const res = await login({
          email: mail,
          password,
          organization_slug: slug,
        });
        await storageSet(LAST_SLUG_KEY, slug);
        await storageSet(LAST_EMAIL_KEY, mail);
        setRememberedSlug(slug);
        await onDone(res.access_token, res.user, res.expires_in);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed";
      const friendly =
        /invalid|credential|401|unauthorized|accept invite/i.test(msg)
          ? msg.includes("Accept invite")
            ? msg
            : "Check company slug, email, and password. Invited teammates use Accept invite or the slug from their manager — not Register."
          : msg;
      Alert.alert("Fos", friendly);
    } finally {
      submitLock.current = false;
      setBusy(false);
    }
  };

  return (
    <Screen scroll>
      <Brand />
      <Sub>Field money. Clear books.</Sub>
      <Sub>
        {mode === "login"
          ? "Joining a team? Use the company slug and password from your manager — or Accept invite with a token."
          : mode === "invite"
            ? "Paste the invite or password-reset token and choose your password."
            : "Creates your organization and owner account."}
      </Sub>
      {!!formError ? <Sub>{formError}</Sub> : null}
      {mode === "login" && (!!rememberedSlug || !!rememberedEmail) && (
        <>
          <Sub>
            Remembered
            {rememberedSlug ? ` company: /${rememberedSlug}` : ""}
            {rememberedEmail ? ` · ${rememberedEmail}` : ""}
          </Sub>
          <LinkText onPress={() => void forgetRemembered()}>Forget remembered</LinkText>
        </>
      )}
      <Card>
        {mode === "invite" ? (
          <>
            <Label>Invite token</Label>
            <Field
              autoCapitalize="none"
              value={inviteToken}
              onChangeText={setInviteToken}
              placeholder="paste token from manager"
              maxLength={128}
            />
            <Label>New password</Label>
            <Field
              secureTextEntry={!showPassword}
              value={password}
              onChangeText={setPassword}
              placeholder="min 8 characters, letter + digit"
              maxLength={128}
            />
            <Label>Confirm password</Label>
            <Field
              secureTextEntry={!showPassword}
              value={passwordConfirm}
              onChangeText={setPasswordConfirm}
              placeholder="repeat password"
              maxLength={128}
            />
            <LinkText onPress={() => setShowPassword((v) => !v)}>
              {showPassword ? "Hide password" : "Show password"}
            </LinkText>
            <Btn title={busy ? "…" : "Accept invite"} onPress={submit} disabled={busy} />
          </>
        ) : (
          <>
            <Label>Organization slug</Label>
            <Field autoCapitalize="none" value={orgSlug} onChangeText={setOrgSlug} placeholder="my-company" maxLength={80} />
            {mode === "register" && (
              <>
                <Label>Company name</Label>
                <Field value={orgName} onChangeText={setOrgName} placeholder="Acme Field Ops" maxLength={200} />
                <Label>Currency</Label>
                <Field autoCapitalize="characters" value={currency} onChangeText={setCurrency} placeholder="IDR" maxLength={3} />
                <Label>Your name</Label>
                <Field value={name} onChangeText={setName} placeholder="Alex" maxLength={200} />
              </>
            )}
            <Label>Email</Label>
            <Field
              autoCapitalize="none"
              keyboardType="email-address"
              value={email}
              onChangeText={setEmail}
              placeholder="you@example.com"
              maxLength={254}
            />
            <Label>Password</Label>
            <Field
              secureTextEntry={!showPassword}
              value={password}
              onChangeText={setPassword}
              placeholder="min 8 characters, letter + digit"
              maxLength={128}
            />
            {mode === "register" && (
              <>
                <Label>Confirm password</Label>
                <Field
                  secureTextEntry={!showPassword}
                  value={passwordConfirm}
                  onChangeText={setPasswordConfirm}
                  placeholder="repeat password"
                  maxLength={128}
                />
              </>
            )}
            <LinkText onPress={() => setShowPassword((v) => !v)}>
              {showPassword ? "Hide password" : "Show password"}
            </LinkText>
            <Btn title={busy ? "…" : mode === "login" ? "Log in" : "Create company"} onPress={submit} disabled={busy} />
            {mode === "login" && DEMO_ENABLED && (
              <Btn title="Use demo workspace" variant="ghost" onPress={fillDemo} disabled={busy} />
            )}
          </>
        )}
      </Card>
      {mode === "login" && (
        <LinkText onPress={() => { setFormError(""); setMode("invite"); }}>Have an invite or reset token?</LinkText>
      )}
      {mode === "invite" && (
        <LinkText onPress={() => { setFormError(""); setMode("login"); }}>Back to log in</LinkText>
      )}
      {mode !== "invite" && (
        <LinkText onPress={() => { setFormError(""); setMode(mode === "login" ? "register" : "login"); }}>
          {mode === "login" ? "New company? Register" : "Have an account? Log in"}
        </LinkText>
      )}
    </Screen>
  );
}
