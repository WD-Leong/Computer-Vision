
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers

def build_model(
    num_classes, backbone_model="resnet50"):
    """
    Builds Backbone Model with pre-trained imagenet weights.
    """
    # Define the focal loss bias. #
    b_focal = tf.constant_initializer(
        np.log(0.01 / 0.99))
    
    # Classification and Regression Feature Layers. #
    cls_cnn = []
    reg_cnn = []
    for n_layer in range(4):
        cls_cnn.append(layers.Conv2D(
            256, 3, padding="same", 
            activation=None, use_bias=False, 
            name="cls_layer_" + str(n_layer+1)))
        
        reg_cnn.append(layers.Conv2D(
            256, 3, padding="same", 
            activation=None, use_bias=False, 
            name="reg_layer_" + str(n_layer+1)))
    
    # Backbone Network. #
    if backbone_model.lower() == "resnet50":
        backbone = tf.keras.applications.ResNet50(
            include_top=False, input_shape=[None, None, 3])
        
        c3_c5_layer_names = [
            "conv3_block4_out", 
            "conv4_block6_out", "conv5_block3_out"]
    elif backbone_model.lower() == "resnet101":
        backbone = tf.keras.applications.ResNet101(
            include_top=False, input_shape=[None, None, 3])
        
        c3_c5_layer_names = [
            "conv3_block4_out", 
            "conv4_block23_out", "conv5_block3_out"]
    else:
        backbone = tf.keras.applications.MobileNetV2(
            include_top=False, input_shape=[None, None, 3])
        
        c3_c5_layer_names = [
            "block_6_expand", "block_13_expand", "Conv_1"]
    
    # Extract the feature maps. #
    c3_output, c4_output, c5_output = [
        backbone.get_layer(layer_name).output
            for layer_name in c3_c5_layer_names]
    
    # Feature Pyramid Network Feature Maps. #
    p3_1x1 = layers.Conv2D(
        256, 1, 1, "same", name="c3_1x1")(c3_output)
    p4_1x1 = layers.Conv2D(
        256, 1, 1, "same", name="c4_1x1")(c4_output)
    p5_1x1 = layers.Conv2D(
        256, 1, 1, "same", name="c5_1x1")(c5_output)
    
    # Residual Connections. #
    p4_residual = p4_1x1 + layers.UpSampling2D(
        size=(2, 2), name="ups_P5")(p5_1x1)
    p3_residual = p3_1x1 + layers.UpSampling2D(
        size=(2, 2), name="ups_P4")(p4_1x1)
    
    p3_output =  layers.Conv2D(
        256, 3, 1, "same", name="c3_3x3")(p3_residual)
    p4_output = layers.Conv2D(
        256, 3, 1, "same", name="c4_3x3")(p4_residual)
    p5_output = layers.Conv2D(
        256, 3, 1, "same", name="c5_3x3")(p5_1x1)
    p6_output = layers.Conv2D(
        256, 3, 2, "same", name="c6_3x3")(c5_output)
    p6_relu   = tf.nn.relu(p6_output)
    p7_output = layers.Conv2D(
        256, 3, 2, "same", name="c7_3x3")(p6_relu)
    fpn_output = [p3_output, p4_output, 
                  p5_output, p6_output, p7_output]
    
    # Output Layers. #
    cls_heads = []
    for n_output in range(len(fpn_output)):
        layer_cls_output = fpn_output[n_output]
        for n_layer in range(4):
            layer_cls_output = \
                cls_cnn[n_layer](layer_cls_output)
        
        tmp_output = tf.nn.relu(layer_cls_output)
        cen_output = layers.Conv2D(
            1, 3, 1, padding="same", 
            bias_initializer=b_focal, 
            name="cen_output_"+str(n_output+1))(tmp_output)
        cls_output = layers.Conv2D(
            num_classes, 3, 1, padding="same",
            bias_initializer=b_focal, 
            name="logits_output_"+str(n_output+1))(tmp_output)
        cls_heads.append(tf.concat([
            cen_output, cls_output], axis=3))
    
    reg_heads = []
    for n_output in range(len(fpn_output)):
        layer_reg_output = fpn_output[n_output]
        for n_layer in range(4):
            layer_reg_output = \
                reg_cnn[n_layer](layer_reg_output)
        
        tmp_output = tf.nn.relu(layer_reg_output)
        reg_output = layers.Conv2D(
            4, 3, 1, padding="same", use_bias=True, 
            name="reg_output_"+str(n_output+1))(tmp_output)
        reg_heads.append(tf.nn.sigmoid(reg_output))
    
    x_output = []
    for n_level in range(len(fpn_output)):
        x_output.append(tf.concat(
            [reg_heads[n_level], 
             cls_heads[n_level]], axis=3))
    return tf.keras.Model(
        inputs=backbone.input, outputs=x_output)

def prediction_to_corners(xy_pred, box_sc, stride):
    feat_dims  = [tf.shape(xy_pred)[0], 
                  tf.shape(xy_pred)[1]]
    bbox_shape = [int(xy_pred.shape[0]), 
                  int(xy_pred.shape[1]), 4]
    bbox_coord = np.zeros(bbox_shape)
    
    ch = tf.range(0., tf.cast(
        feat_dims[0], tf.float32), dtype=tf.float32)
    cw = tf.range(0., tf.cast(
        feat_dims[1], tf.float32), dtype=tf.float32)
    [grid_x, grid_y] = tf.meshgrid(cw, ch)
    
    pred_x_cen = (grid_x + xy_pred[..., 1]) * stride
    pred_y_cen = (grid_y + xy_pred[..., 0]) * stride
    pred_box_w = xy_pred[..., 3] * box_sc
    pred_box_h = xy_pred[..., 2] * box_sc
    
    bbox_coord[:, :, 0] = pred_y_cen - pred_box_h / 2.0
    bbox_coord[:, :, 2] = pred_y_cen + pred_box_h / 2.0
    bbox_coord[:, :, 1] = pred_x_cen - pred_box_w / 2.0
    bbox_coord[:, :, 3] = pred_x_cen + pred_box_w / 2.0
    return bbox_coord

def format_data(
    gt_labels, img_dim, num_classes, img_pad=None, 
    b_dim=None, strides=None, center_only=False):
    """
    gt_labels: Normalised Gound Truth Bounding Boxes (y, x, h, w).
    num_targets is for debugging purposes.
    """
    if strides is None:
        strides = [8, 16, 32, 64, 128]
    
    if b_dim is None:
        b_dim = [32, 64, 128, 256]
    
    if img_pad is None:
        img_pad = img_dim
    
    gt_height = gt_labels[:, 2]*img_dim[0]
    gt_width  = gt_labels[:, 3]*img_dim[1]
    gt_height = gt_height.numpy()
    gt_width  = gt_width.numpy()
    
    num_targets = []
    tmp_outputs = []
    for na in range(len(strides)):
        stride  = strides[na]
        h_ratio = img_dim[0] / stride
        w_ratio = img_dim[1] / stride
        
        h_max = int(img_pad[0] / stride)
        w_max = int(img_pad[1] / stride)
        tmp_output = np.zeros([
            h_max, w_max, num_classes+5])
        
        if na == 0:
            box_sc  = b_dim[0]
            tmp_idx = [
                x for x in range(len(gt_labels)) if \
                max(gt_width[x], gt_height[x]) < b_dim[0]]
        elif na == len(strides)-1:
            box_sc  = max(img_dim[0], img_dim[1])
            tmp_idx = [
                x for x in range(len(gt_labels)) if \
                max(gt_width[x], gt_height[x]) >= b_dim[-1]]
        else:
            box_sc  = b_dim[na]
            tmp_idx = [x for x in range(len(gt_labels)) if \
                max(gt_width[x], gt_height[x]) >= b_dim[na-1] \
                and max(gt_width[x], gt_height[x]) < b_dim[na]]
        
        if len(tmp_idx) == 0:
            num_targets.append(0)
            tmp_outputs.append(tmp_output)
        else:
            # Sort the labels by area from largest to smallest.     #
            # Then the smallest area will automatically overwrite   #
            # any overlapping grid positions since it is the last   #
            # to be filled up.                                      #
            
            # For FCOS, fill up all grid positions which the bounding #
            # box occupies in the feature map. Note that we also clip #
            # the (l, r, t, b) values as it may have negative values  #
            # due to the integer floor operation. This could cause    #
            # the (l, r, t, b) computation to return negative values  #
            # and usually occurs when the object is near or at the    #
            # edge of the image.                                      #
            
            tmp_labels = gt_labels.numpy()[tmp_idx, :]
            if len(tmp_labels) == 1:
                tmp_sorted = tmp_labels
            else:
                tmp_box_areas = np.multiply(
                    tmp_labels[:, 2]*img_dim[0], 
                    tmp_labels[:, 3]*img_dim[1])
                
                tmp_sorted = \
                    tmp_labels[np.argsort(tmp_box_areas)]
            
            for n_label in range(len(tmp_sorted)):
                tmp_label = tmp_sorted[n_label]
                
                box_h = tmp_label[2]*img_dim[0]
                box_w = tmp_label[3]*img_dim[1]
                
                raw_y_cen = tmp_label[0] * img_dim[0]
                raw_x_cen = tmp_label[1] * img_dim[1]
                tmp_y_cen = int(raw_y_cen / stride)
                tmp_x_cen = int(raw_x_cen / stride)
                tmp_y_off = \
                    (raw_y_cen - tmp_y_cen*stride) / stride
                tmp_x_off = \
                    (raw_x_cen - tmp_x_cen*stride) / stride
                idx_class = 5 + int(tmp_label[4])
                
                # Bounding Box Regression Outputs. #
                box_reg = [
                    tmp_y_off, tmp_x_off, 
                    box_h / box_sc, box_w / box_sc]
                
                # Assign the regression values at the object centroid. #
                tmp_output[tmp_y_cen, tmp_x_cen, :4] = box_reg
                
                # Assign the center score at the centroid to be 1. #
                tmp_output[tmp_y_cen, tmp_x_cen, 4] = 1.0
                
                # Assign the label at the centroid to be 1. #
                tmp_output[tmp_y_cen, tmp_x_cen, idx_class] = 1.0
            
            num_targets.append(len(tmp_labels))
            tmp_outputs.append(tmp_output)
    return tmp_outputs, num_targets

def smooth_l1_loss(xy_true, xy_pred, mask=1.0, delta=1.0):
    mask = tf.expand_dims(mask, axis=-1)
    raw_diff = xy_true - xy_pred
    sq_diff  = tf.square(raw_diff)
    abs_diff = tf.abs(raw_diff)
    
    smooth_l1_loss = tf.where(
        tf.less(abs_diff, delta), 
        0.5 * sq_diff, abs_diff)
    smooth_l1_loss = tf.reduce_sum(tf.reduce_sum(
        tf.multiply(smooth_l1_loss, mask), axis=-1))
    return smooth_l1_loss

def focal_loss(
    labels, logits, alpha=0.25, gamma=2.0):
    labels = tf.cast(labels, tf.float32)
    tmp_log_logits  = tf.math.log(1.0 + tf.exp(-1.0 * tf.abs(logits)))
    
    tmp_abs_term = tf.math.add(
        tf.multiply(labels * alpha * tmp_log_logits, 
                    tf.pow(1.0 - tf.nn.sigmoid(logits), gamma)), 
        tf.multiply(tf.pow(tf.nn.sigmoid(logits), gamma), 
                    (1.0 - labels) * (1.0 - alpha) * tmp_log_logits))
    
    tmp_x_neg = tf.multiply(
        labels * alpha * tf.minimum(logits, 0), 
        tf.pow(1.0 - tf.nn.sigmoid(logits), gamma))
    tmp_x_pos = tf.multiply(
        (1.0 - labels) * (1.0 - alpha), 
        tf.maximum(logits, 0) * tf.pow(tf.nn.sigmoid(logits), gamma))
    
    foc_loss_stable = tmp_abs_term + tmp_x_pos - tmp_x_neg
    return tf.reduce_sum(foc_loss_stable)

def model_loss(y_true, y_pred):
    """
    y_true: Normalised Gound Truth Bounding Boxes (x, y, w, h).
    """
    cen_loss = 0.0
    cls_loss = 0.0
    reg_loss = 0.0
    for n_scale in range(len(y_pred)):
        tmp_obj  = tf.reduce_max(
            y_true[n_scale][..., 5:], axis=-1)
        tmp_mask = tf.cast(tmp_obj >= 1, tf.float32)
        
        cls_loss += focal_loss(
            y_true[n_scale][..., 5:], 
            y_pred[n_scale][0][..., 5:])
        
        cen_loss += focal_loss(
            y_true[n_scale][..., 4], 
            y_pred[n_scale][0][..., 4])
        
        reg_loss += smooth_l1_loss(
            y_true[n_scale][..., :4], 
            y_pred[n_scale][0][..., :4], mask=tmp_mask)
    return cls_loss, reg_loss, cen_loss

    
