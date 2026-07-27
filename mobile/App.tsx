import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { StatusBar } from "expo-status-bar";
import {
  clearToken,
  createRecord,
  decideRecord,
  getToken,
  inviteUser,
  login,
  me,
  myBalance,
  myRecords,
  pendingRecords,
  registerOrg,
  saveToken,
  type MoneyRecord,
  type User,
} from "./src/api";

type Screen = "boot" | "auth" | "home" | "create" | "approve" | "invite";

export default function App() {
  const [screen, setScreen] = useState<Screen>("boot");
  const [user, setUser] = useState<User | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const token = await getToken();
        if (!token) {
          setScreen("auth");
          return;
        }
        const u = await me();
        setUser(u);
        setScreen("home");
      } catch {
        await clearToken();
        setScreen("auth");
      }
    })();
  }, []);

  if (screen === "boot") {
    return (
      <View style={styles.center}>
        <ActivityIndicator color="#1DB954" />
        <StatusBar style="light" />
      </View>
    );
  }

  if (screen === "auth") {
    return (
      <AuthScreen
        busy={busy}
        setBusy={setBusy}
        onDone={async (token, u) => {
          await saveToken(token);
          setUser(u);
          setScreen("home");
        }}
      />
    );
  }

  if (screen === "create" && user) {
    return (
      <CreateScreen
        busy={busy}
        setBusy={setBusy}
        onBack={() => setScreen("home")}
        onCreated={() => setScreen("home")}
      />
    );
  }

  if (screen === "approve" && user) {
    return (
      <ApproveScreen
        busy={busy}
        setBusy={setBusy}
        onBack={() => setScreen("home")}
      />
    );
  }

  if (screen === "invite" && user) {
    return (
      <InviteScreen
        busy={busy}
        setBusy={setBusy}
        currentRole={user.role}
        onBack={() => setScreen("home")}
        onDone={() => setScreen("home")}
      />
    );
  }

  return (
    <HomeScreen
      user={user}
      onCreate={() => setScreen("create")}
      onApprove={() => setScreen("approve")}
      onInvite={() => setScreen("invite")}
      onLogout={async () => {
        await clearToken();
        setUser(null);
        setScreen("auth");
      }}
    />
  );
}

function AuthScreen({
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
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");

  const submit = async () => {
    setBusy(true);
    try {
      if (mode === "register") {
        const res = await registerOrg({
          name: orgName,
          slug: orgSlug.toLowerCase(),
          owner_email: email,
          owner_name: name,
          owner_password: password,
        });
        onDone(res.access_token, res.user);
      } else {
        const res = await login({
          email,
          password,
          organization_slug: orgSlug.toLowerCase(),
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
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.brand}>Fos</Text>
        <Text style={styles.sub}>Field money. Clear books.</Text>
        <View style={styles.card}>
          <Text style={styles.label}>Organization slug</Text>
          <TextInput style={styles.input} autoCapitalize="none" value={orgSlug} onChangeText={setOrgSlug} placeholder="my-company" placeholderTextColor="#5A7A6A" />
          {mode === "register" && (
            <>
              <Text style={styles.label}>Company name</Text>
              <TextInput style={styles.input} value={orgName} onChangeText={setOrgName} />
              <Text style={styles.label}>Your name</Text>
              <TextInput style={styles.input} value={name} onChangeText={setName} />
            </>
          )}
          <Text style={styles.label}>Email</Text>
          <TextInput style={styles.input} autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
          <Text style={styles.label}>Password</Text>
          <TextInput style={styles.input} secureTextEntry value={password} onChangeText={setPassword} />
          <Pressable style={styles.btn} onPress={submit} disabled={busy}>
            <Text style={styles.btnText}>{busy ? "…" : mode === "login" ? "Log in" : "Create company"}</Text>
          </Pressable>
          <Pressable onPress={() => setMode(mode === "login" ? "register" : "login")}>
            <Text style={styles.link}>
              {mode === "login" ? "New company? Register" : "Have an account? Log in"}
            </Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function HomeScreen({
  user,
  onCreate,
  onApprove,
  onInvite,
  onLogout,
}: {
  user: User | null;
  onCreate: () => void;
  onApprove: () => void;
  onInvite: () => void;
  onLogout: () => void;
}) {
  const [balance, setBalance] = useState<string>("—");
  const [rows, setRows] = useState<MoneyRecord[]>([]);

  const reload = async () => {
    try {
      const b = await myBalance();
      setBalance(`${b.cash_on_hand.toLocaleString()} ${b.currency} · ${b.pending_count} pending`);
      setRows(await myRecords());
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Load failed");
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const isManager = user?.role === "owner" || user?.role === "manager";

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <View style={styles.topRow}>
        <View>
          <Text style={styles.brandSmall}>Fos</Text>
          <Text style={styles.sub}>{user?.full_name} · {user?.role}</Text>
        </View>
        <Pressable onPress={onLogout}><Text style={styles.link}>Log out</Text></Pressable>
      </View>
      <View style={styles.card}>
        <Text style={styles.label}>Cash on hand</Text>
        <Text style={styles.balance}>{balance}</Text>
      </View>
      <View style={styles.rowBtns}>
        <Pressable style={styles.btn} onPress={onCreate}><Text style={styles.btnText}>New record</Text></Pressable>
        {isManager && (
          <Pressable style={[styles.btn, styles.btnSecondary]} onPress={onApprove}>
            <Text style={styles.btnText}>Approvals</Text>
          </Pressable>
        )}
      </View>
      {isManager && (
        <Pressable style={[styles.btn, styles.btnGhost]} onPress={onInvite}>
          <Text style={styles.btnGhostText}>Invite teammate</Text>
        </Pressable>
      )}
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{ paddingBottom: 40 }}
        ListHeaderComponent={<Text style={styles.section}>My records</Text>}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.rowTitle}>{item.kind} · {item.status}</Text>
            <Text style={styles.rowMeta}>{item.amount} {item.currency} · {item.category || "—"}</Text>
          </View>
        )}
      />
    </SafeAreaView>
  );
}

function CreateScreen({
  busy,
  setBusy,
  onBack,
  onCreated,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState<"expense" | "fuel" | "income">("expense");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [comment, setComment] = useState("");
  const [liters, setLiters] = useState("");
  const [odometer, setOdometer] = useState("");
  const [clientName, setClientName] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<"cash" | "transfer">("cash");

  const submit = async () => {
    const value = Number(amount.replace(",", "."));
    if (!value || value <= 0) {
      Alert.alert("Fos", "Enter a valid amount");
      return;
    }
    setBusy(true);
    try {
      await createRecord({
        kind,
        amount: value,
        category,
        comment,
        payment_method: kind === "income" ? paymentMethod : "",
        client_name: kind === "income" ? clientName : "",
        liters: kind === "fuel" && liters ? Number(liters.replace(",", ".")) : undefined,
        odometer: kind === "fuel" && odometer ? Number(odometer.replace(",", ".")) : undefined,
      });
      onCreated();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <View style={styles.topRow}>
        <Pressable onPress={onBack}><Text style={styles.linkLeft}>← Back</Text></Pressable>
        <Pressable onPress={onBack}><Text style={styles.link}>Cancel</Text></Pressable>
      </View>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.brandSmall}>New record</Text>
        <View style={styles.kinds}>
          {(["expense", "fuel", "income"] as const).map((k) => (
            <Pressable key={k} style={[styles.chip, kind === k && styles.chipOn]} onPress={() => setKind(k)}>
              <Text style={styles.chipText}>{k}</Text>
            </Pressable>
          ))}
        </View>
        <Text style={styles.label}>Amount</Text>
        <TextInput style={styles.input} keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
        <Text style={styles.label}>Category</Text>
        <TextInput style={styles.input} value={category} onChangeText={setCategory} />
        {kind === "fuel" && (
          <>
            <Text style={styles.label}>Liters</Text>
            <TextInput style={styles.input} keyboardType="decimal-pad" value={liters} onChangeText={setLiters} />
            <Text style={styles.label}>Odometer</Text>
            <TextInput style={styles.input} keyboardType="decimal-pad" value={odometer} onChangeText={setOdometer} />
          </>
        )}
        {kind === "income" && (
          <>
            <Text style={styles.label}>Client name</Text>
            <TextInput style={styles.input} value={clientName} onChangeText={setClientName} />
            <Text style={styles.label}>Payment method</Text>
            <View style={styles.kinds}>
              {(["cash", "transfer"] as const).map((m) => (
                <Pressable key={m} style={[styles.chip, paymentMethod === m && styles.chipOn]} onPress={() => setPaymentMethod(m)}>
                  <Text style={styles.chipText}>{m}</Text>
                </Pressable>
              ))}
            </View>
          </>
        )}
        <Text style={styles.label}>Comment</Text>
        <TextInput style={styles.input} value={comment} onChangeText={setComment} />
        <Pressable style={styles.btn} onPress={submit} disabled={busy}>
          <Text style={styles.btnText}>{busy ? "…" : "Submit"}</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

function ApproveScreen({
  busy,
  setBusy,
  onBack,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
}) {
  const [rows, setRows] = useState<MoneyRecord[]>([]);

  const reload = async () => {
    try {
      setRows(await pendingRecords());
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const decide = async (id: number, approve: boolean) => {
    setBusy(true);
    try {
      await decideRecord(id, approve);
      await reload();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <View style={styles.topRow}>
        <Pressable onPress={onBack}><Text style={styles.linkLeft}>← Back</Text></Pressable>
        <Pressable onPress={onBack}><Text style={styles.link}>Cancel</Text></Pressable>
      </View>
      <Text style={styles.brandSmall}>Approvals</Text>
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        ListEmptyComponent={<Text style={styles.sub}>No pending records</Text>}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.rowTitle}>{item.kind} · {item.amount} {item.currency}</Text>
            <Text style={styles.rowMeta}>{item.category || item.comment || "—"}</Text>
            <View style={styles.rowBtns}>
              <Pressable style={styles.btn} disabled={busy} onPress={() => decide(item.id, true)}>
                <Text style={styles.btnText}>Approve</Text>
              </Pressable>
              <Pressable style={[styles.btn, styles.btnDanger]} disabled={busy} onPress={() => decide(item.id, false)}>
                <Text style={styles.btnText}>Reject</Text>
              </Pressable>
            </View>
          </View>
        )}
      />
    </SafeAreaView>
  );
}

function InviteScreen({
  busy,
  setBusy,
  currentRole,
  onBack,
  onDone,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  currentRole: User["role"];
  onBack: () => void;
  onDone: () => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"employee" | "manager" | "owner">("employee");
  const roles =
    currentRole === "owner"
      ? (["employee", "manager", "owner"] as const)
      : (["employee", "manager"] as const);

  const submit = async () => {
    if (!email.trim() || !fullName.trim() || password.length < 6) {
      Alert.alert("Fos", "Name, email, and password (6+) required");
      return;
    }
    setBusy(true);
    try {
      await inviteUser({
        email: email.trim(),
        full_name: fullName.trim(),
        role,
        password,
      });
      Alert.alert("Fos", "Teammate invited");
      onDone();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <View style={styles.topRow}>
        <Pressable onPress={onBack}><Text style={styles.linkLeft}>← Back</Text></Pressable>
        <Pressable onPress={onBack}><Text style={styles.link}>Cancel</Text></Pressable>
      </View>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.brandSmall}>Invite teammate</Text>
        <Text style={styles.label}>Full name</Text>
        <TextInput style={styles.input} value={fullName} onChangeText={setFullName} />
        <Text style={styles.label}>Email</Text>
        <TextInput style={styles.input} autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
        <Text style={styles.label}>Password</Text>
        <TextInput style={styles.input} secureTextEntry value={password} onChangeText={setPassword} />
        <Text style={styles.label}>Role</Text>
        <View style={styles.kinds}>
          {roles.map((r) => (
            <Pressable key={r} style={[styles.chip, role === r && styles.chipOn]} onPress={() => setRole(r)}>
              <Text style={styles.chipText}>{r}</Text>
            </Pressable>
          ))}
        </View>
        <Pressable style={styles.btn} onPress={submit} disabled={busy}>
          <Text style={styles.btnText}>{busy ? "…" : "Send invite"}</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#0B1F1A", padding: 20 },
  scroll: { paddingBottom: 40 },
  center: { flex: 1, backgroundColor: "#0B1F1A", alignItems: "center", justifyContent: "center" },
  brand: { color: "#E8F5E9", fontSize: 42, fontWeight: "700", marginTop: 24 },
  brandSmall: { color: "#E8F5E9", fontSize: 28, fontWeight: "700", marginVertical: 12 },
  sub: { color: "#9CB5A8", marginBottom: 16 },
  card: { backgroundColor: "#132E26", borderRadius: 16, padding: 16, marginBottom: 16 },
  label: { color: "#9CB5A8", marginBottom: 6, marginTop: 8 },
  input: {
    backgroundColor: "#0B1F1A",
    color: "#E8F5E9",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: "#1F4A3C",
  },
  btn: {
    backgroundColor: "#1DB954",
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 16,
    alignItems: "center",
    marginTop: 12,
    flex: 1,
  },
  btnSecondary: { backgroundColor: "#2E7D57" },
  btnDanger: { backgroundColor: "#B33A3A" },
  btnGhost: {
    backgroundColor: "transparent",
    borderWidth: 1,
    borderColor: "#1F4A3C",
    flex: 0,
    marginBottom: 8,
  },
  btnText: { color: "#04140F", fontWeight: "700" },
  btnGhostText: { color: "#7DDBA3", fontWeight: "700" },
  link: { color: "#7DDBA3", marginTop: 14, textAlign: "center" },
  linkLeft: { color: "#7DDBA3", marginTop: 14, textAlign: "left" },
  balance: { color: "#E8F5E9", fontSize: 22, fontWeight: "700" },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  rowBtns: { flexDirection: "row", gap: 10, marginBottom: 8 },
  section: { color: "#E8F5E9", fontWeight: "600", marginBottom: 8 },
  row: { backgroundColor: "#132E26", borderRadius: 12, padding: 12, marginBottom: 8 },
  rowTitle: { color: "#E8F5E9", fontWeight: "600" },
  rowMeta: { color: "#9CB5A8", marginTop: 4 },
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  chip: { paddingVertical: 8, paddingHorizontal: 12, borderRadius: 20, backgroundColor: "#132E26" },
  chipOn: { backgroundColor: "#1DB954" },
  chipText: { color: "#E8F5E9", fontWeight: "600" },
});
