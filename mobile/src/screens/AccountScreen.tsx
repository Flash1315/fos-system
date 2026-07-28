import React, { useEffect, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import {
  changePassword,
  listSettlementRequests,
  listMySettlementRequests,
  myBalance,
  myOrg,
  requestSettlement,
  approveSettlementRequest,
  cancelSettlementRequest,
  updateOrg,
  type User,
} from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";

type ReqRow = {
  id: number;
  user_name: string;
  kind: string;
  amount: number;
  note: string;
  status?: string;
  settled_amount?: number | null;
  payout_id?: number | null;
};

export function AccountScreen({
  user,
  busy,
  setBusy,
  onBack,
}: {
  user: User;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
}) {
  const isManager = user.role === "owner" || user.role === "manager";
  const isOwner = user.role === "owner";
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [kind, setKind] = useState<"expense_payout" | "income_handover">("income_handover");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [requests, setRequests] = useState<ReqRow[]>([]);
  const [mine, setMine] = useState<ReqRow[]>([]);
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [currency, setCurrency] = useState("RUB");
  const [cancelId, setCancelId] = useState<number | null>(null);

  const reloadOrg = async () => {
    try {
      const org = await myOrg();
      setOrgName(org.name);
      setOrgSlug(org.slug);
      setCurrency(org.currency || "RUB");
    } catch {
      /* ignore */
    }
  };

  const reloadRequests = async () => {
    try {
      setMine(await listMySettlementRequests());
    } catch {
      setMine([]);
    }
    if (!isManager) return;
    try {
      setRequests(await listSettlementRequests());
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    (async () => {
      await reloadOrg();
      try {
        const b = await myBalance();
        const available =
          kind === "expense_payout"
            ? (b.available_spendings ?? b.spendings)
            : (b.available_cash ?? b.cash_on_hand);
        setAmount(available > 0 ? String(available) : "");
      } catch {
        /* ignore */
      }
      await reloadRequests();
    })();
  }, [kind]);

  const onPassword = async () => {
    if (!current || next.length < 6) {
      Alert.alert("Fos", "Enter current password and new password (min 6)");
      return;
    }
    setBusy(true);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      Alert.alert("Fos", "Password updated");
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const onSaveOrg = async () => {
    if (!orgName.trim()) {
      Alert.alert("Fos", "Company name required");
      return;
    }
    setBusy(true);
    try {
      const org = await updateOrg({ name: orgName.trim(), currency: currency.trim() || "RUB" });
      setOrgName(org.name);
      setCurrency(org.currency);
      Alert.alert("Fos", "Company updated");
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const onRequest = async () => {
    const value = Number(amount.replace(",", "."));
    if (!value || value <= 0) {
      Alert.alert("Fos", "Enter amount");
      return;
    }
    setBusy(true);
    try {
      await requestSettlement({ kind, amount: value, note });
      Alert.alert("Fos", "Settlement request sent to managers");
      setNote("");
      await reloadRequests();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Label>Account</Label>
      <Sub>
        {user.full_name} · {user.email} · {user.role}
      </Sub>
      <Sub>
        {orgName || "…"}
        {orgSlug ? ` · /${orgSlug}` : ""}
      </Sub>

      {isOwner && (
        <>
          <Label>Company settings</Label>
          <Sub>
            Owners can rename the company. Currency can change only before the first money record or
            settlement. Slug stays fixed for login.
          </Sub>
          <Field value={orgName} onChangeText={setOrgName} placeholder="Company name" />
          <Field
            value={currency}
            onChangeText={setCurrency}
            placeholder="Currency (RUB)"
            autoCapitalize="characters"
          />
          <Btn title={busy ? "…" : "Save company"} onPress={onSaveOrg} disabled={busy} />
        </>
      )}

      <Label>Change password</Label>
      <Field secureTextEntry value={current} onChangeText={setCurrent} placeholder="Current password" />
      <Field secureTextEntry value={next} onChangeText={setNext} placeholder="New password" />
      <Btn title={busy ? "…" : "Update password"} onPress={onPassword} disabled={busy} />

      <Label>Request settlement</Label>
      <Sub>
        Amount defaults to available balance (track minus pending requests). Ask a manager to pay
        spendings or take cash on hand.
      </Sub>
      <View style={styles.kinds}>
        <Chip
          label="Pay my spendings"
          on={kind === "expense_payout"}
          onPress={() => setKind("expense_payout")}
        />
        <Chip
          label="Hand over cash"
          on={kind === "income_handover"}
          onPress={() => setKind("income_handover")}
        />
      </View>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <Field value={note} onChangeText={setNote} placeholder="Optional note" />
      <Btn title={busy ? "…" : "Send request"} onPress={onRequest} disabled={busy} />

      <Label>My requests</Label>
      {mine.length === 0 ? (
        <Sub>None yet</Sub>
      ) : (
        mine.map((r) => (
          <View key={r.id} style={styles.card}>
            <Sub>
              {r.kind} · {r.amount.toLocaleString()} · {r.status || "pending"}
              {r.settled_amount != null ? ` · settled ${r.settled_amount.toLocaleString()}` : ""}
              {r.note ? ` · ${r.note}` : ""}
            </Sub>
            {r.status === "pending" && (
              <Btn
                title="Cancel request"
                variant="ghost"
                disabled={busy}
                onPress={async () => {
                  setBusy(true);
                  try {
                    await cancelSettlementRequest(r.id);
                    await reloadRequests();
                  } catch (e) {
                    Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
                  } finally {
                    setBusy(false);
                  }
                }}
              />
            )}
          </View>
        ))
      )}

      {isManager && (
        <>
          <Label>Team pending requests</Label>
          {requests.length === 0 ? (
            <Sub>None</Sub>
          ) : (
            requests.map((r) => (
              <View key={r.id} style={styles.card}>
                <Sub>
                  {r.user_name} · {r.kind} · {r.amount.toLocaleString()}
                  {r.note ? ` · ${r.note}` : ""}
                </Sub>
                <View style={styles.kinds}>
                  <Btn
                    title="Approve"
                    disabled={busy}
                    onPress={async () => {
                      setBusy(true);
                      try {
                        await approveSettlementRequest(r.id);
                        await reloadRequests();
                      } catch (e) {
                        Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
                      } finally {
                        setBusy(false);
                      }
                    }}
                  />
                  <Btn
                    title="Cancel"
                    variant="ghost"
                    disabled={busy}
                    onPress={() => setCancelId(r.id)}
                  />
                </View>
              </View>
            ))
          )}
        </>
      )}
      <NoteModal
        visible={cancelId != null}
        title="Cancel teammate request"
        onCancel={() => setCancelId(null)}
        onSubmit={async (cancelNote) => {
          if (!cancelNote.trim()) {
            Alert.alert("Fos", "Cancel requires a note");
            return;
          }
          const id = cancelId;
          setCancelId(null);
          if (id == null) return;
          setBusy(true);
          try {
            await cancelSettlementRequest(id, cancelNote.trim());
            await reloadRequests();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            setBusy(false);
          }
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  card: { marginBottom: 12 },
});
