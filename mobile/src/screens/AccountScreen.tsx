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
  const [currency, setCurrency] = useState("IDR");
  const [currencyLocked, setCurrencyLocked] = useState(false);
  const [orgLoadError, setOrgLoadError] = useState("");
  const [orgLoaded, setOrgLoaded] = useState(false);
  const [cancelId, setCancelId] = useState<number | null>(null);
  const [teamReqFilter, setTeamReqFilter] = useState<"pending" | "approved" | "cancelled" | "all">(
    "pending",
  );
  const [mineReqFilter, setMineReqFilter] = useState<"all" | "pending" | "approved" | "cancelled">(
    "all",
  );
  const [reqLoadError, setReqLoadError] = useState("");

  const reloadOrg = async () => {
    try {
      setOrgLoadError("");
      const org = await myOrg();
      setOrgName(org.name);
      setOrgSlug(org.slug);
      setCurrency(org.currency || "IDR");
      setCurrencyLocked(!!org.currency_locked);
      setOrgLoaded(true);
    } catch (e) {
      setOrgLoaded(false);
      setOrgLoadError(e instanceof Error ? e.message : "Failed to load company");
    }
  };

  const reloadRequests = async () => {
    setReqLoadError("");
    try {
      setMine(
        await listMySettlementRequests(
          mineReqFilter === "all" ? undefined : { status: mineReqFilter },
        ),
      );
    } catch (e) {
      setMine([]);
      setReqLoadError(e instanceof Error ? e.message : "Failed to load requests");
    }
    if (!isManager) return;
    try {
      setRequests(await listSettlementRequests({ status: teamReqFilter }));
    } catch (e) {
      setRequests([]);
      setReqLoadError(e instanceof Error ? e.message : "Failed to load team requests");
    }
  };

  const refreshSuggestedAmount = async () => {
    try {
      const b = await myBalance();
      const available =
        kind === "expense_payout"
          ? (b.available_spendings ?? b.spendings)
          : (b.available_cash ?? b.cash_on_hand);
      setAmount(available > 0 ? String(available) : "");
    } catch {
      setAmount("");
    }
  };

  useEffect(() => {
    (async () => {
      await reloadOrg();
      await refreshSuggestedAmount();
      await reloadRequests();
    })();
  }, [kind, teamReqFilter, mineReqFilter]);

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
    if (busy) return;
    if (!orgName.trim()) {
      Alert.alert("Fos", "Company name required");
      return;
    }
    setBusy(true);
    try {
      const fresh = await myOrg();
      setCurrencyLocked(!!fresh.currency_locked);
      const payload: { name: string; currency?: string } = { name: orgName.trim() };
      if (!fresh.currency_locked) {
        payload.currency = currency.trim() || "IDR";
      } else {
        setCurrency(fresh.currency || currency);
      }
      const org = await updateOrg(payload);
      setOrgName(org.name);
      setCurrency(org.currency);
      setCurrencyLocked(!!org.currency_locked);
      Alert.alert("Fos", "Company updated");
    } catch (e) {
      try {
        const fresh = await myOrg();
        setCurrency(fresh.currency);
        setCurrencyLocked(!!fresh.currency_locked);
      } catch {
        /* ignore */
      }
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
    const label =
      kind === "expense_payout"
        ? `Request expense reimbursement ${value.toLocaleString()} ${currency}?`
        : `Request cash handover ${value.toLocaleString()} ${currency}?`;
    Alert.alert("Fos", label, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Send",
        onPress: async () => {
          setBusy(true);
          try {
            await requestSettlement({ kind, amount: value, note });
            Alert.alert("Fos", "Settlement request sent to managers");
            setNote("");
            await refreshSuggestedAmount();
            await reloadRequests();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  const doApproveRequest = async (id: number, paymentMethod: "cash" | "transfer") => {
    if (busy) return;
    setBusy(true);
    try {
      await reloadRequests();
      await approveSettlementRequest(id, paymentMethod);
      await reloadRequests();
      await refreshSuggestedAmount();
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
      {!!orgLoadError && (
        <>
          <Sub>Could not load company — {orgLoadError}</Sub>
          <Btn title="Retry" variant="ghost" onPress={reloadOrg} />
        </>
      )}

      {isOwner && orgLoaded && (
        <>
          <Label>Company settings</Label>
          <Sub>
            Owners can rename the company. Currency can change only before the first money record,
            settlement, or balance adjustment. Slug stays fixed for login.
          </Sub>
          <Field value={orgName} onChangeText={setOrgName} placeholder="Company name" />
          <Field
            value={currency}
            onChangeText={setCurrency}
            placeholder="Currency (IDR)"
            autoCapitalize="characters"
            editable={!currencyLocked}
          />
          {currencyLocked ? (
            <Sub>Currency locked after money activity — rename only.</Sub>
          ) : null}
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
          label="Expense reimbursement"
          on={kind === "expense_payout"}
          onPress={() => setKind("expense_payout")}
        />
        <Chip
          label="Cash handover"
          on={kind === "income_handover"}
          onPress={() => setKind("income_handover")}
        />
      </View>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <Field value={note} onChangeText={setNote} placeholder="Optional note" />
      <Btn title={busy ? "…" : "Send request"} onPress={onRequest} disabled={busy} />

      <Label>My requests</Label>
      {!!reqLoadError && <Sub>Could not load — {reqLoadError}</Sub>}
      <View style={styles.kinds}>
        {(["all", "pending", "approved", "cancelled"] as const).map((s) => (
          <Chip
            key={s}
            label={s}
            on={mineReqFilter === s}
            onPress={() => setMineReqFilter(s)}
          />
        ))}
      </View>
      {mine.length === 0 ? (
        <Sub>{mineReqFilter === "all" ? "None yet" : `No ${mineReqFilter} requests`}</Sub>
      ) : (
        mine.map((r) => (
          <View key={r.id} style={styles.card}>
            <Sub>
              {r.kind} · {r.amount.toLocaleString()} {currency} · {r.status || "pending"}
              {r.settled_amount != null
                ? ` · settled ${r.settled_amount.toLocaleString()} ${currency}`
                : ""}
              {r.note ? ` · ${r.note}` : ""}
            </Sub>
            {r.status === "pending" && (
              <Btn
                title="Cancel request"
                variant="ghost"
                disabled={busy}
                onPress={() => {
                  Alert.alert("Fos", "Cancel this settlement request?", [
                    { text: "Keep", style: "cancel" },
                    {
                      text: "Cancel request",
                      style: "destructive",
                      onPress: async () => {
                        setBusy(true);
                        try {
                          await cancelSettlementRequest(r.id);
                          await refreshSuggestedAmount();
                          await reloadRequests();
                        } catch (e) {
                          Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
                        } finally {
                          setBusy(false);
                        }
                      },
                    },
                  ]);
                }}
              />
            )}
          </View>
        ))
      )}

      {isManager && (
        <>
          <Label>Team requests</Label>
          <View style={styles.kinds}>
            {(["pending", "approved", "cancelled", "all"] as const).map((s) => (
              <Chip
                key={s}
                label={s}
                on={teamReqFilter === s}
                onPress={() => setTeamReqFilter(s)}
              />
            ))}
          </View>
          {requests.length === 0 ? (
            <Sub>{teamReqFilter === "all" ? "None" : `No ${teamReqFilter} requests`}</Sub>
          ) : (
            requests.map((r) => (
              <View key={r.id} style={styles.card}>
                <Sub>
                  {r.user_name} · {r.kind} · {r.amount.toLocaleString()} {currency} ·{" "}
                  {r.status || "pending"}
                  {r.note ? ` · ${r.note}` : ""}
                </Sub>
                {r.status === "pending" && (
                  <View style={styles.kinds}>
                    <Btn
                      title="Approve"
                      disabled={busy}
                      onPress={() => {
                        const label =
                          r.kind === "expense_payout"
                            ? "expense reimbursement"
                            : "cash handover";
                        Alert.alert(
                          "Fos",
                          `Approve ${label} ${r.amount.toLocaleString()} ${currency} for ${r.user_name}? Choose payment method:`,
                          [
                            { text: "Cancel", style: "cancel" },
                            {
                              text: "Cash",
                              onPress: () => void doApproveRequest(r.id, "cash"),
                            },
                            {
                              text: "Transfer",
                              onPress: () => void doApproveRequest(r.id, "transfer"),
                            },
                          ],
                        );
                      }}
                    />
                    <Btn
                      title="Cancel"
                      variant="ghost"
                      disabled={busy}
                      onPress={() => setCancelId(r.id)}
                    />
                  </View>
                )}
              </View>
            ))
          )}
        </>
      )}
      <NoteModal
        visible={cancelId != null}
        title="Cancel teammate request"
        required
        onCancel={() => setCancelId(null)}
        onSubmit={async (cancelNote) => {
          const id = cancelId;
          setCancelId(null);
          if (id == null) return;
          setBusy(true);
          try {
            await cancelSettlementRequest(id, cancelNote);
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
