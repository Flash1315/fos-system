import React, { useEffect, useRef, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import {
  billingMe,
  changePassword,
  listSettlementRequests,
  listMySettlementRequests,
  makeIdempotencyKey,
  myBalance,
  myOrg,
  requestSettlement,
  approveSettlementRequest,
  cancelSettlementRequest,
  saveToken,
  setTelegramChat,
  testTelegram,
  updateOrg,
  type BillingInfo,
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
  const [nextConfirm, setNextConfirm] = useState("");
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
  const [billing, setBilling] = useState<BillingInfo | null>(null);
  const [tgChat, setTgChat] = useState("");
  const [mineHasMore, setMineHasMore] = useState(false);
  const [teamHasMore, setTeamHasMore] = useState(false);
  const [loadingMoreMine, setLoadingMoreMine] = useState(false);
  const [loadingMoreTeam, setLoadingMoreTeam] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const PAGE = 40;
  const requestIdemRef = useRef<string | null>(null);
  const approveIdemRef = useRef<string | null>(null);
  const approveSlotRef = useRef<number | null>(null);
  const cancelIdemRef = useRef<string | null>(null);
  const cancelSlotRef = useRef<number | null>(null);

  const reloadOrg = async () => {
    try {
      setOrgLoadError("");
      const org = await myOrg();
      setOrgName(org.name);
      setOrgSlug(org.slug);
      setCurrency(org.currency || "IDR");
      setCurrencyLocked(!!org.currency_locked);
      setOrgLoaded(true);
      if (isOwner) {
        try {
          const b = await billingMe();
          setBilling(b);
          setTgChat(b.telegram_chat_id || "");
        } catch {
          setBilling(null);
        }
      }
    } catch (e) {
      setOrgLoaded(false);
      setOrgLoadError(e instanceof Error ? e.message : "Failed to load company");
    }
  };

  const reloadRequests = async () => {
    setReqLoadError("");
    try {
      const mineRows = await listMySettlementRequests({
        ...(mineReqFilter === "all" ? {} : { status: mineReqFilter }),
        limit: PAGE,
        offset: 0,
      });
      setMine(mineRows);
      setMineHasMore(mineRows.length >= PAGE);
    } catch (e) {
      setMine([]);
      setMineHasMore(false);
      setReqLoadError(e instanceof Error ? e.message : "Failed to load requests");
    }
    if (!isManager) return;
    try {
      const teamRows = await listSettlementRequests({
        status: teamReqFilter,
        limit: PAGE,
        offset: 0,
      });
      setRequests(teamRows);
      setTeamHasMore(teamRows.length >= PAGE);
    } catch (e) {
      setRequests([]);
      setTeamHasMore(false);
      setReqLoadError(e instanceof Error ? e.message : "Failed to load team requests");
    }
  };

  const loadMoreMine = async () => {
    if (loadingMoreMine || !mineHasMore) return;
    setLoadingMoreMine(true);
    try {
      const more = await listMySettlementRequests({
        ...(mineReqFilter === "all" ? {} : { status: mineReqFilter }),
        limit: PAGE,
        offset: mine.length,
      });
      setMine((prev) => [...prev, ...more]);
      setMineHasMore(more.length >= PAGE);
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Load more failed");
    } finally {
      setLoadingMoreMine(false);
    }
  };

  const loadMoreTeam = async () => {
    if (loadingMoreTeam || !teamHasMore || !isManager) return;
    setLoadingMoreTeam(true);
    try {
      const more = await listSettlementRequests({
        status: teamReqFilter,
        limit: PAGE,
        offset: requests.length,
      });
      setRequests((prev) => [...prev, ...more]);
      setTeamHasMore(more.length >= PAGE);
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Load more failed");
    } finally {
      setLoadingMoreTeam(false);
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

  const onPullRefresh = async () => {
    setRefreshing(true);
    try {
      await reloadOrg();
      await refreshSuggestedAmount();
      await reloadRequests();
    } finally {
      setRefreshing(false);
    }
  };

  const onPassword = async () => {
    if (busy) return;
    if (!current || next.length < 6) {
      Alert.alert("Fos", "Enter current password and new password (min 6)");
      return;
    }
    if (next !== nextConfirm) {
      Alert.alert("Fos", "Passwords do not match");
      return;
    }
    setBusy(true);
    try {
      const res = await changePassword(current, next, nextConfirm);
      await saveToken(res.access_token);
      setCurrent("");
      setNext("");
      setNextConfirm("");
      Alert.alert("Fos", "Password updated — other sessions signed out");
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
    if (busy) return;
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
          if (busy) return;
          if (!requestIdemRef.current) requestIdemRef.current = makeIdempotencyKey("sreq");
          setBusy(true);
          try {
            await requestSettlement(
              { kind, amount: value, note },
              { idempotencyKey: requestIdemRef.current },
            );
            requestIdemRef.current = null;
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
    if (approveSlotRef.current !== id) {
      approveSlotRef.current = id;
      approveIdemRef.current = null;
    }
    if (!approveIdemRef.current) approveIdemRef.current = makeIdempotencyKey("appr");
    setBusy(true);
    try {
      await reloadRequests();
      await approveSettlementRequest(id, paymentMethod, {
        idempotencyKey: approveIdemRef.current,
      });
      approveIdemRef.current = null;
      approveSlotRef.current = null;
      await reloadRequests();
      await refreshSuggestedAmount();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen scroll refreshing={refreshing} onRefresh={() => void onPullRefresh()}>
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

          <Label>Plan & integrations</Label>
          <Sub>
            Plan is informational until billing goes live. Optional Telegram chat for org alerts when
            the server has TELEGRAM_BOT_TOKEN. SMTP invites when SMTP_HOST is set.
          </Sub>
          {billing && (
            <Sub>
              Plan {billing.plan} · {billing.billing_status} · media {billing.media_backend}
              {billing.email_configured ? " · email on" : " · email off"}
              {billing.telegram_configured ? " · telegram bot on" : " · telegram bot off"}
            </Sub>
          )}
          <Label>Telegram chat id</Label>
          <Field value={tgChat} onChangeText={setTgChat} placeholder="-100…" autoCapitalize="none" />
          <Btn
            title={busy ? "…" : "Save Telegram chat"}
            variant="ghost"
            disabled={busy}
            onPress={async () => {
              setBusy(true);
              try {
                const b = await setTelegramChat(tgChat.trim());
                setBilling(b);
                Alert.alert("Fos", "Telegram chat saved");
              } catch (e) {
                Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
              } finally {
                setBusy(false);
              }
            }}
          />
          <Btn
            title="Send Telegram test"
            variant="ghost"
            disabled={busy}
            onPress={async () => {
              setBusy(true);
              try {
                await testTelegram();
                Alert.alert("Fos", "Test message sent");
              } catch (e) {
                Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
              } finally {
                setBusy(false);
              }
            }}
          />
        </>
      )}

      <Label>Change password</Label>
      <Field secureTextEntry value={current} onChangeText={setCurrent} placeholder="Current password" />
      <Field secureTextEntry value={next} onChangeText={setNext} placeholder="New password" />
      <Field
        secureTextEntry
        value={nextConfirm}
        onChangeText={setNextConfirm}
        placeholder="Confirm new password"
      />
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
                        if (cancelSlotRef.current !== r.id) {
                          cancelSlotRef.current = r.id;
                          cancelIdemRef.current = null;
                        }
                        if (!cancelIdemRef.current) {
                          cancelIdemRef.current = makeIdempotencyKey("scancel");
                        }
                        setBusy(true);
                        try {
                          await cancelSettlementRequest(r.id, "", {
                            idempotencyKey: cancelIdemRef.current,
                          });
                          cancelIdemRef.current = null;
                          cancelSlotRef.current = null;
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
      {mineHasMore ? (
        <Btn
          title={loadingMoreMine ? "…" : "Load more"}
          variant="ghost"
          disabled={loadingMoreMine}
          onPress={() => void loadMoreMine()}
        />
      ) : null}

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
          {teamHasMore ? (
            <Btn
              title={loadingMoreTeam ? "…" : "Load more"}
              variant="ghost"
              disabled={loadingMoreTeam}
              onPress={() => void loadMoreTeam()}
            />
          ) : null}
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
          if (cancelSlotRef.current !== id) {
            cancelSlotRef.current = id;
            cancelIdemRef.current = null;
          }
          if (!cancelIdemRef.current) cancelIdemRef.current = makeIdempotencyKey("scancel");
          setBusy(true);
          try {
            await cancelSettlementRequest(id, cancelNote, {
              idempotencyKey: cancelIdemRef.current,
            });
            cancelIdemRef.current = null;
            cancelSlotRef.current = null;
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
