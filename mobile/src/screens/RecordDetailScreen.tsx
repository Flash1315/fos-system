import React, { useRef, useState } from "react";
import { Alert, Image, Text, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import {
  cancelRecord,
  commentRecord,
  decideRecord,
  getRecord,
  makeIdempotencyKey,
  mediaUrlWithMediaToken,
  updateRecord,
  voidRecord,
  type MoneyRecord,
  type User,
} from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Card, Chip, Field, Label, Row, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen, statusColor } from "../format";
import { colors } from "../theme";

const PURPOSES = ["Rental", "Lesson", "Office", "Other"] as const;

export function RecordDetailScreen({
  id,
  user,
  busy,
  setBusy,
  onBack,
}: {
  id: number;
  user: User;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
}) {
  const [rec, setRec] = useState<MoneyRecord | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [commentOpen, setCommentOpen] = useState(false);
  const [voidOpen, setVoidOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editAmount, setEditAmount] = useState("");
  const [editPlace, setEditPlace] = useState("");
  const [editComment, setEditComment] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [editPurpose, setEditPurpose] = useState("Other");
  const [editPaymentSource, setEditPaymentSource] = useState<"my_pocket" | "cash_on_hand">(
    "my_pocket",
  );
  const [editPaymentMethod, setEditPaymentMethod] = useState<"cash" | "transfer">("cash");
  const [editClient, setEditClient] = useState("");
  const [editLiters, setEditLiters] = useState("");
  const [editOdometer, setEditOdometer] = useState("");
  const [editBike, setEditBike] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [photoUri, setPhotoUri] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const cancelIdemRef = useRef<string | null>(null);
  const commentIdemRef = useRef<string | null>(null);
  const decideIdemRef = useRef<string | null>(null);
  const decideSlotRef = useRef<string | null>(null);
  const voidIdemRef = useRef<string | null>(null);
  const isManager = user.role === "owner" || user.role === "manager";

  const applyEditFields = (row: MoneyRecord) => {
    setEditAmount(String(row.amount));
    setEditPlace(row.place || "");
    setEditComment(row.comment || "");
    setEditCategory(row.category || "");
    setEditPurpose(row.purpose || "Other");
    setEditPaymentSource(
      row.payment_source === "cash_on_hand" ? "cash_on_hand" : "my_pocket",
    );
    setEditPaymentMethod(row.payment_method === "transfer" ? "transfer" : "cash");
    setEditClient(row.client_name || "");
    setEditLiters(row.liters != null ? String(row.liters) : "");
    setEditOdometer(row.odometer != null ? String(row.odometer) : "");
    setEditBike(row.bike || "");
  };

  const reload = async (opts?: { preserveEdits?: boolean }) => {
    try {
      setLoadError("");
      const row = await getRecord(id);
      setRec(row);
      if (!opts?.preserveEdits) {
        applyEditFields(row);
      }
      if (row.photo_url) {
        setPhotoUri(await mediaUrlWithMediaToken(row.photo_url));
      } else {
        setPhotoUri("");
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed");
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(false);
    }
  };

  useFocusEffect(() => {
    void reload();
  });

  const onPullRefresh = async () => {
    setRefreshing(true);
    try {
      await reload({ preserveEdits: editing });
    } finally {
      setRefreshing(false);
    }
  };

  const decide = async (approve: boolean, note = "") => {
    if (approve && rec?.created_by_active === false) {
      Alert.alert("Fos", "Cannot approve — teammate is inactive. Reject instead.");
      return;
    }
    if (approve && rec?.is_in_closed_cycle) {
      Alert.alert(
        "Fos",
        `This belongs to a settled period${
          rec.settlement_cutoff_at ? ` (cutoff ${formatWhen(rec.settlement_cutoff_at)})` : ""
        }. Approving will not change the current balance. Continue?`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Approve anyway",
            onPress: () => void doDecide(true, note),
          },
        ],
      );
      return;
    }
    if (approve) {
      Alert.alert("Fos", "Approve this record?", [
        { text: "Cancel", style: "cancel" },
        { text: "Approve", onPress: () => void doDecide(true, note) },
      ]);
      return;
    }
    await doDecide(approve, note);
  };

  const doDecide = async (approve: boolean, note = "") => {
    if (busy) return;
    const slot = approve ? "a" : "r";
    if (decideSlotRef.current !== slot) {
      decideSlotRef.current = slot;
      decideIdemRef.current = null;
    }
    if (!decideIdemRef.current) decideIdemRef.current = makeIdempotencyKey("decide");
    setBusy(true);
    try {
      setRec(await decideRecord(id, approve, note, { idempotencyKey: decideIdemRef.current }));
      decideIdemRef.current = null;
      decideSlotRef.current = null;
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const onCancel = async () => {
    if (busy) return;
    Alert.alert("Fos", "Cancel this pending record? It will be removed from approvals.", [
      { text: "Keep", style: "cancel" },
      {
        text: "Cancel record",
        style: "destructive",
        onPress: async () => {
          setBusy(true);
          try {
            const fresh = await getRecord(id);
            setRec(fresh);
            applyEditFields(fresh);
            if (fresh.status !== "pending") {
              Alert.alert("Fos", `Record is already ${fresh.is_voided ? "voided" : fresh.status}`);
              return;
            }
            if (!cancelIdemRef.current) cancelIdemRef.current = makeIdempotencyKey("cancel");
            setRec(await cancelRecord(id, { idempotencyKey: cancelIdemRef.current }));
            cancelIdemRef.current = null;
            Alert.alert("Fos", "Record cancelled");
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  const onVoid = async (note: string) => {
    if (busy) return;
    setBusy(true);
    try {
      const fresh = await getRecord(id);
      setRec(fresh);
      applyEditFields(fresh);
      if (fresh.is_voided) {
        Alert.alert("Fos", "Record is already voided");
        return;
      }
      if (!fresh.can_void) {
        Alert.alert("Fos", fresh.void_blocked_reason || "This record cannot be voided now");
        return;
      }
      if (!voidIdemRef.current) voidIdemRef.current = makeIdempotencyKey("void");
      setRec(await voidRecord(id, note, { idempotencyKey: voidIdemRef.current }));
      voidIdemRef.current = null;
      Alert.alert("Fos", "Record voided");
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const onComment = async (note: string) => {
    setBusy(true);
    try {
      if (!commentIdemRef.current) commentIdemRef.current = makeIdempotencyKey("cmt");
      setRec(await commentRecord(id, note, { idempotencyKey: commentIdemRef.current }));
      commentIdemRef.current = null;
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const onSaveEdit = async () => {
    const value = Number(editAmount.replace(",", "."));
    if (!value || value <= 0) {
      Alert.alert("Fos", "Enter a valid amount");
      return;
    }
    if (!editCategory.trim()) {
      Alert.alert("Fos", "Category is required");
      return;
    }
    const body: Parameters<typeof updateRecord>[1] = {
      amount: value,
      place: editPlace,
      comment: editComment,
      category: editCategory.trim(),
    };
    if (rec?.kind === "expense" || rec?.kind === "fuel") {
      body.purpose = editPurpose;
      body.payment_source = editPaymentSource;
    }
    if (rec?.kind === "income") {
      body.payment_method = editPaymentMethod;
      body.client_name = editClient;
      if (editPurpose) body.purpose = editPurpose;
    }
    if (rec?.kind === "fuel") {
      body.bike = editBike.trim();
      const liters = Number(editLiters.replace(",", "."));
      const odo = Number(editOdometer.replace(",", "."));
      if (!editLiters.trim() || !Number.isFinite(liters) || liters <= 0) {
        Alert.alert("Fos", "Liters is required for fuel");
        return;
      }
      body.liters = liters;
      if (editOdometer.trim()) {
        if (!Number.isFinite(odo) || odo < 0) {
          Alert.alert("Fos", "Odometer must be a finite number");
          return;
        }
        body.odometer = odo;
      }
    }
    setBusy(true);
    try {
      const updated = await updateRecord(id, body);
      setRec(updated);
      applyEditFields(updated);
      setEditing(false);
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const canCancel =
    !!rec &&
    rec.status === "pending" &&
    (rec.created_by === user.id || isManager);
  const canEdit =
    !!rec &&
    rec.status === "pending" &&
    (rec.created_by === user.id || isManager);
  const canVoid = !!rec && isManager && !!rec.can_void;

  return (
    <Screen scroll refreshing={refreshing} onRefresh={() => void onPullRefresh()}>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Record #{id}</Text>
      {loading && !rec ? (
        <Sub>Loading...</Sub>
      ) : loadError && !rec ? (
        <>
          <Sub>Could not load — {loadError}</Sub>
          <Btn title="Retry" variant="ghost" onPress={reload} />
        </>
      ) : !rec ? (
        <Sub>Record not found</Sub>
      ) : (
        <>
          <Card>
            <Label>Kind / status</Label>
            <Text style={styles.line}>
              {rec.kind} ·{" "}
              <Text style={{ color: statusColor(rec.status, !!rec.is_voided) }}>
                {rec.is_voided ? "voided" : rec.status}
              </Text>
            </Text>
            <Label>Amount</Label>
            <Text style={styles.big}>{formatMoney(rec.amount, rec.currency)}</Text>
            <Label>Purpose</Label>
            <Text style={styles.line}>{rec.purpose || "—"}</Text>
            <Label>Category</Label>
            <Text style={styles.line}>{rec.category || "—"}</Text>
            <Label>Place</Label>
            <Text style={styles.line}>{rec.place || "—"}</Text>
            {!!rec.bike && (
              <>
                <Label>Bike</Label>
                <Text style={styles.line}>{rec.bike}</Text>
              </>
            )}
            {!!rec.payment_source && (
              <>
                <Label>Payment source</Label>
                <Text style={styles.line}>
                  {rec.payment_source === "my_pocket" ? "My pocket" : "Cash on hand"}
                </Text>
              </>
            )}
            <Label>By</Label>
            <Text style={styles.line}>
              {rec.created_by_name || rec.created_by}
              {rec.created_by_active === false ? " · Inactive" : ""} ·{" "}
              {formatWhen(rec.created_at)}
            </Text>
            {!!rec.occurred_at && (
              <>
                <Label>Occurred</Label>
                <Text style={styles.line}>{formatWhen(rec.occurred_at)}</Text>
              </>
            )}
            {!!rec.is_in_closed_cycle && (
              <>
                <Label>Settlement cycle</Label>
                <Text style={styles.line}>
                  Falls in a settled period
                  {rec.settlement_cutoff_at
                    ? ` (cutoff ${formatWhen(rec.settlement_cutoff_at)})`
                    : ""}
                  . Does not change the current open balance.
                </Text>
              </>
            )}
            {!!rec.client_name && (
              <>
                <Label>Client</Label>
                <Text style={styles.line}>
                  {rec.client_name} · {rec.payment_method || "—"}
                </Text>
              </>
            )}
            {(rec.liters != null || rec.odometer != null) && (
              <>
                <Label>Fuel</Label>
                <Text style={styles.line}>
                  {rec.liters ?? "—"} L · odo {rec.odometer ?? "—"}
                </Text>
              </>
            )}
            {!!rec.transfer_group_id && (
              <>
                <Label>Transfer pair</Label>
                <Text style={styles.line}>
                  Linked transfer {rec.transfer_group_id} — voiding reverses both legs
                </Text>
              </>
            )}
            <Label>Comment</Label>
            <Text style={styles.line}>{rec.comment || "—"}</Text>
            {!!rec.decided_at && (
              <>
                <Label>Decided</Label>
                <Text style={styles.line}>
                  {formatWhen(rec.decided_at)}
                  {rec.decided_by_name ? ` · ${rec.decided_by_name}` : ""}
                </Text>
              </>
            )}
            {!!rec.voided_at && (
              <>
                <Label>Voided</Label>
                <Text style={styles.line}>{formatWhen(rec.voided_at)}</Text>
              </>
            )}
          </Card>
          {!!rec.photo_url && !!photoUri && (
            <Card>
              <Label>Receipt</Label>
              <Image source={{ uri: photoUri }} style={styles.photo} />
            </Card>
          )}
          {isManager && rec.status === "pending" && (
            <Row>
              <Btn
                title={rec.created_by_active === false ? "Inactive" : "Approve"}
                disabled={busy || rec.created_by_active === false}
                onPress={() => decide(true)}
              />
              <Btn title="Reject" variant="danger" disabled={busy} onPress={() => setRejectOpen(true)} />
            </Row>
          )}
          {canEdit && !editing && (
            <Btn title="Edit pending" variant="ghost" disabled={busy} onPress={() => setEditing(true)} />
          )}
          {canEdit && editing && (
            <Card>
              <Label>Edit amount</Label>
              <Field keyboardType="decimal-pad" value={editAmount} onChangeText={setEditAmount} />
              <Label>Category</Label>
              <Field value={editCategory} onChangeText={setEditCategory} />
              {(rec.kind === "expense" || rec.kind === "fuel") && (
                <>
                  <Label>Purpose</Label>
                  <Row>
                    {PURPOSES.map((p) => (
                      <Chip key={p} label={p} on={editPurpose === p} onPress={() => setEditPurpose(p)} />
                    ))}
                  </Row>
                  <Label>Payment source</Label>
                  <Row>
                    <Chip
                      label="My pocket"
                      on={editPaymentSource === "my_pocket"}
                      onPress={() => setEditPaymentSource("my_pocket")}
                    />
                    <Chip
                      label="Cash on hand"
                      on={editPaymentSource === "cash_on_hand"}
                      onPress={() => setEditPaymentSource("cash_on_hand")}
                    />
                  </Row>
                </>
              )}
              {rec.kind === "income" && (
                <>
                  <Label>Payment method</Label>
                  <Row>
                    <Chip
                      label="Cash"
                      on={editPaymentMethod === "cash"}
                      onPress={() => setEditPaymentMethod("cash")}
                    />
                    <Chip
                      label="Transfer"
                      on={editPaymentMethod === "transfer"}
                      onPress={() => setEditPaymentMethod("transfer")}
                    />
                  </Row>
                  <Label>Client</Label>
                  <Field value={editClient} onChangeText={setEditClient} />
                </>
              )}
              {rec.kind === "fuel" && (
                <>
                  <Label>Bike</Label>
                  <Field value={editBike} onChangeText={setEditBike} />
                  <Label>Liters</Label>
                  <Field keyboardType="decimal-pad" value={editLiters} onChangeText={setEditLiters} />
                  <Label>Odometer</Label>
                  <Field
                    keyboardType="decimal-pad"
                    value={editOdometer}
                    onChangeText={setEditOdometer}
                  />
                </>
              )}
              <Label>Place</Label>
              <Field value={editPlace} onChangeText={setEditPlace} />
              <Label>Comment</Label>
              <Field value={editComment} onChangeText={setEditComment} />
              <Row>
                <Btn title="Save" disabled={busy} onPress={onSaveEdit} />
                <Btn title="Cancel edit" variant="ghost" onPress={() => setEditing(false)} />
              </Row>
            </Card>
          )}
          {canCancel && (
            <Btn title="Cancel record" variant="ghost" disabled={busy} onPress={onCancel} />
          )}
          {canVoid && (
            <Btn title="Void approved" variant="danger" disabled={busy} onPress={() => setVoidOpen(true)} />
          )}
          {isManager &&
            !!rec &&
            rec.status === "approved" &&
            !rec.is_voided &&
            !rec.can_void &&
            !!rec.void_blocked_reason && <Sub>{rec.void_blocked_reason}</Sub>}
          {isManager && (
            <Btn
              title="Add manager note"
              variant="ghost"
              disabled={busy}
              onPress={() => setCommentOpen(true)}
            />
          )}
        </>
      )}
      <NoteModal
        visible={rejectOpen}
        title="Reject record"
        required
        onCancel={() => setRejectOpen(false)}
        onSubmit={async (note) => {
          setRejectOpen(false);
          await decide(false, note);
        }}
      />
      <NoteModal
        visible={voidOpen}
        title={
          rec?.transfer_group_id
            ? "Void transfer (both legs)"
            : "Void approved record"
        }
        label="Reason (required). Void removes this from balances."
        required
        confirmTitle="Void"
        confirmVariant="danger"
        onCancel={() => setVoidOpen(false)}
        onSubmit={async (note) => {
          setVoidOpen(false);
          await onVoid(note);
        }}
      />
      <NoteModal
        visible={commentOpen}
        title="Manager note"
        required
        onCancel={() => setCommentOpen(false)}
        onSubmit={async (note) => {
          setCommentOpen(false);
          await onComment(note);
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  line: { color: colors.text, marginTop: 2 },
  big: { color: colors.text, fontSize: 22, fontWeight: "700" },
  photo: { width: "100%", height: 220, borderRadius: 12, marginTop: 8, backgroundColor: colors.cardAlt },
});
