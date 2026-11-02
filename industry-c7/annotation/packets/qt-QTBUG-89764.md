# Annotation packet: QTBUG-89764  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Vulkan: Sync validation reports WAW hazard with point/spot light shadows

{code}
vkDebug: Validation: 0: Validation Error: [ SYNC-HAZARD-WRITE_AFTER_WRITE ] Object 0: handle = 0x100c000000100c, type = VK_OBJECT_TYPE_RENDER_PASS; | MessageID = 0xfdf9f5e1 | vkCmdBeginRenderPass: Hazard WRITE_AFTER_WRITE in subpass 0 for attachment 1 image layout transition (old_layout: VK_IMAGE_LAYOUT_UNDEFINED, new_layout: VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL). Access info (usage: SYNC_IMAGE_LAYOUT_TRANSITION, prior_usage: SYNC_LATE_FRAGMENT_TESTS_DEPTH_STENCIL_ATTACHMENT_WRITE, write_barriers: 0, command: vkCmdEndRenderPass, seq_no: 6, reset_no: 123).
{code}

(SDK 1.2.154, sync validation enabled with vkconfig)
```

## Fix commit message(s)

`f0d1a50333f3`

```
(empty)
```

## Files the fix changed

Snapshot holds 5,847 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `src/gui/rhi/qrhivulkan.cpp`
- `src/gui/rhi/qrhivulkan_p_p.h`

## The fix diff

### `src/gui/rhi/qrhivulkan.cpp`

```diff
(no diff retrieved)
```

### `src/gui/rhi/qrhivulkan_p_p.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
