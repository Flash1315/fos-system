import React, { useState } from "react";
import { Alert } from "react-native";
import { login, registerOrg, type User } from "../api";
import { Brand, Btn, Card, Field, Label, LinkText, Screen, Sub } from "../components/ui";

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

  const submit = async () => {
    setBusy(true);
    try {
      if (mode === "register") {
        const res = await registerOrg({
          name: orgName,
          slug: orgSlug.toLowerCase().trim(),
          currency: currency.trim().toUpperCase() || "IDR",
          owner_email: email,
          owner_name: name,
          owner_password: password,
        });
        onDone(res.access_token, res.user);
      } else {
        const res = await login({
          email,
          password,
          organization_slug: orgSlug.toLowerCase().trim(),
        });
        onDone(res.access_token, res.user);
      }
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
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
          ? "First time? Tap Register below to create your company."
          : "Creates your organization and owner account."}
      </Sub>
      <Card>
        <Label>Organization slug</Label>
        <Field autoCapitalize="none" value={orgSlug} onChangeText={setOrgSlug} placeholder="my-company" />
        {mode === "register" && (
          <>
            <Label>Company name</Label>
            <Field value={orgName} onChangeText={setOrgName} placeholder="My Company" />
            <Label>Currency</Label>
            <Field autoCapitalize="characters" value={currency} onChangeText={setCurrency} placeholder="IDR" />
            <Label>Your name</Label>
            <Field value={name} onChangeText={setName} placeholder="Owner name" />
          </>
        )}
        <Label>Email</Label>
        <Field autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} placeholder="you@example.com" />
        <Label>Password</Label>
        <Field secureTextEntry value={password} onChangeText={setPassword} placeholder="min 6 characters" />
        <Btn title={busy ? "…" : mode === "login" ? "Log in" : "Create company"} onPress={submit} disabled={busy} />
        <LinkText onPress={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "New company? Register" : "Have an account? Log in"}
        </LinkText>
      </Card>
    </Screen>
  );
}
