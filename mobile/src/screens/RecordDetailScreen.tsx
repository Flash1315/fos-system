import React, { useEffect, useRef, useState } from "react";
import { Alert, Image, Text, StyleSheet } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { useFocusEffect } from "../useFocus";
import {
  cancelRecord,
  commentRecord,
  decideRecord,
  getRecord,
  idemKeyFor,
  lastFuelOdometer,
  makeIdempotencyKey,
  mediaUrlWithMediaToken,
  updateRecord,
  uploadPhoto,
  voidRecord,
  type MoneyRecord,
  type User,
} from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Card, Chip, Field, Label, Row, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen, parseFiniteLiters, parseFiniteMoney, parseFiniteOdometer, statusColor } from "../format";
import { isValidYmd, ymdError } from "../dates";
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
  const [editOccurred, setEditOccurred] = useState("");
  const [editPhotoUrl, setEditPhotoUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [photoUri, setPhotoUri] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const cancelIdemRef = useRef<string | null>(null);
  const commentIdemRef = useRef<string | null>(null);
  const commentSlotRef = useRef<string | null>(null);
  const decideIdemRef = useRef<string | null>(null);
  const decideSlotRef = useRef<string | null>(null);
  const voidIdemRef = useRef<string | null>(null);
  const voidSlotRef = useRef<string | null>(null);
  const editIdemRef = useRef<string | null>(null);
  const reloadGen = useRef(0);
  const isManager = user.role === "owner" || user.role === "manager";

  useEffect(() => {
    editIdemRef.current = null;
  }, [
    editAmount,
    editPlace,
    editComment,
    editCategory,
    editPurpose,
    editPaymentSource,
    editPaymentMethod,
    editClient,
    editLiters,
    editOdometer,
    editBike,
    editOccurred,
    editPhotoUrl,
  ]);

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
    setEditOccurred(row.occurred_at ? String(row.occurred_at).slice(0, 10) : "");
    setEditPhotoUrl(row.photo_url || "");
  };

  const reload = async (opts?: { preserveEdits?: boolean }) => {
    const gen = ++reloadGen.current;
    try {
      setLoadError("");
      const row = await getRecord(id);
      if (gen !== reloadGen.current) return;
      setRec(row);
      if (!opts?.preserveEdits) {
        applyEditFields(row);
      }
      if (row.photo_url) {
        const uri = await mediaUrlWithMediaToken(row.photo_url);
        if (gen !== reloadGen.current) return;
        setPhotoUri(uri);
      } else {
        setPhotoUri("");
      }
    } catch (e) {
      if (gen !== reloadGen.current) return;
      setLoadError(e instanceof Error ? e.message : "Failed");
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      if (gen === reloadGen.current) setLoading(false);
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
    const noteKey = note.replace(/\s+/g, " ").trim();
    const key = idemKeyFor(
      decideIdemRef,
      decideSlotRef,
      "decide",
      `${approve ? "a" : "r"}:${noteKey}`,
    );
    setBusy(true);
    try {
      reloadGen.current += 1;
      setRec(await decideRecord(id, approve, note, { idempotencyKey: key }));
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
            reloadGen.current += 1;
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
      const noteKey = note.replace(/\s+/g, " ").trim();
      const key = idemKeyFor(voidIdemRef, voidSlotRef, "void", `${id}:${noteKey}`);
      reloadGen.current += 1;
      setRec(await voidRecord(id, note, { idempotencyKey: key }));
      voidIdemRef.current = null;
      voidSlotRef.current = null;
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
      const noteKey = note.replace(/\s+/g, " ").trim();
      const key = idemKeyFor(commentIdemRef, commentSlotRef, "cmt", `${id}:${noteKey}`);
      reloadGen.current += 1;
      setRec(await commentRecord(id, note, { idempotencyKey: key }));
      commentIdemRef.current = null;
      commentSlotRef.current = null;
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const onSaveEdit = async () => {
    const value = parseFiniteMoney(editAmount);
    if (value == null) {
      Alert.alert("Fos", "Enter a valid amount");
      return;
    }
    if (!editCategory.trim()) {
      Alert.alert("Fos", "Category is required");
      return;
    }
    if (editComment.trim().length > 4000) {
      Alert.alert("Fos", "Comment is too long (max 4000 characters)");
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
      const liters = parseFiniteLiters(editLiters);
      if (liters == null) {
        Alert.alert("Fos", "Liters is required for fuel (max 10000)");
        return;
      }
      body.liters = liters;
      const when = editOccurred.trim();
      const at = when ? `${when}T12:00:00` : undefined;
      try {
        const hint = await lastFuelOdometer({
          bike: editBike.trim() || undefined,
          user_id: rec.created_by,
          at,
          exclude_id: rec.id,
        });
        const odoRaw = editOdometer.trim();
        if (hint.has_history && !odoRaw) {
          Alert.alert(
            "Fos",
            `Odometer is required after prior fuel history${
              hint.odometer != null ? ` (last ${hint.odometer})` : ""
            }`,
          );
          return;
        }
        if (odoRaw) {
          const odo = parseFiniteOdometer(odoRaw);
          if (odo == null) {
            Alert.alert("Fos", "Odometer must be a valid reading (0–9999999.99)");
            return;
          }
          if (hint.min_odometer != null && odo < hint.min_odometer) {
            Alert.alert(
              "Fos",
              `Odometer cannot decrease (previous ${hint.min_odometer}).`,
            );
            return;
          }
          if (hint.max_odometer != null && odo > hint.max_odometer) {
            Alert.alert(
              "Fos",
              `Odometer cannot jump past the next reading (${hint.max_odometer}).`,
            );
            return;
          }
          body.odometer = odo;
        }
      } catch (e) {
        Alert.alert("Fos", e instanceof Error ? e.message : "Could not verify odometer");
        return;
      }
    }
    const when = editOccurred.trim();
    if (when) {
      const err = ymdError(when, "When");
      if (err) {
        Alert.alert("Fos", err);
        return;
      }
      body.occurred_at = `${when}T12:00:00`;
    } else {
      body.occurred_at = null;
    }
    if (editPhotoUrl !== (rec?.photo_url || "")) {
      body.photo_url = editPhotoUrl || "";
    }
    if (!editIdemRef.current) editIdemRef.current = makeIdempotencyKey("rupd");
    setBusy(true);
    try {
      const updated = await updateRecord(id, body, { idempotencyKey: editIdemRef.current });
      editIdemRef.current = null;
      reloadGen.current += 1;
      setRec(updated);
      applyEditFields(updated);
      setEditing(false);
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const pickEditPhoto = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Fos", "Photo permission required");
      return;
    }
    const shot = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      quality: 0.7,
    });
    if (shot.canceled || !shot.assets[0]) return;
    const asset = shot.assets[0];
    const mime = (asset.mimeType || "").toLowerCase();
    const fname = (asset.fileName || asset.uri || "").toLowerCase();
    if (
      mime.includes("heic") ||
      mime.includes("heif") ||
      fname.endsWith(".heic") ||
      fname.endsWith(".heif")
    ) {
      Alert.alert("Fos", "HEIC/HEIF is not supported. Choose JPEG, PNG, or WebP.");
      return;
    }
    setBusy(true);
    try {
      const up = await uploadPhoto(asset.uri, {
        name: asset.fileName || undefined,
        type: asset.mimeType || undefined,
      });
      setEditPhotoUrl(up.photo_url);
      setPhotoUri(await mediaUrlWithMediaToken(up.photo_url));
      Alert.alert("Fos", "Receipt photo ready — tap Save to apply");
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const canCancel =
    !!rec &&
    rec.status === "pending" &&
    rec.created_by === user.id;
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
              <Field keyboardType="decimal-pad" value={editAmount} onChangeText={setEditAmount} maxLength={24} />
              <Label>Category</Label>
              <Field value={editCategory} onChangeText={setEditCategory} maxLength={120} />
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
                  <Field value={editClient} onChangeText={setEditClient} maxLength={200} />
                </>
              )}
              {rec.kind === "fuel" && (
                <>
                  <Label>Bike</Label>
                  <Field value={editBike} onChangeText={setEditBike} maxLength={120} />
                  <Label>Liters</Label>
                  <Field keyboardType="decimal-pad" value={editLiters} onChangeText={setEditLiters} maxLength={12} />
                  <Label>Odometer</Label>
                  <Field
                    keyboardType="decimal-pad"
                    value={editOdometer}
                    onChangeText={setEditOdometer}
                    maxLength={12}
                  />
                </>
              )}
              <Label>Place</Label>
              <Field value={editPlace} onChangeText={setEditPlace} maxLength={200} />
              <Label>When (optional YYYY-MM-DD)</Label>
              <Field
                autoCapitalize="none"
                value={editOccurred}
                onChangeText={setEditOccurred}
                placeholder="leave empty = clear"
                maxLength={10}
              />
              <Label>Receipt photo</Label>
              <Sub>{editPhotoUrl ? "Attached" : "None"}</Sub>
              <Row>
                <Btn title="Replace photo" variant="ghost" disabled={busy} onPress={() => void pickEditPhoto()} />
                {!!editPhotoUrl && (
                  <Btn
                    title="Remove photo"
                    variant="ghost"
                    disabled={busy}
                    onPress={() => {
                      setEditPhotoUrl("");
                      setPhotoUri("");
                    }}
                  />
                )}
              </Row>
              <Label>Comment</Label>
              <Field value={editComment} onChangeText={setEditComment} maxLength={4000} />
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
        maxLength={2000}
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
        maxLength={2000}
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
        maxLength={2000}
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
