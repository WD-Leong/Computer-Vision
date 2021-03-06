
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers

def center_dist_1d(grid_x, mu_x=0.0, spread=2.0):
    gauss_x = np.divide(
        1.0, np.power(grid_x-mu_x, spread))
    Z_norm  = tf.reduce_max(gauss_x)
    return gauss_x / Z_norm

def center_dist_2d(
    grid_x, grid_y, mu_x=0.0, mu_y=0.0, spread=2.0):
    gauss_x = np.divide(
        1.0, np.power(grid_x-mu_x, spread))
    gauss_y = np.divide(
        1.0, np.power(grid_y-mu_y, spread))
    Z_norm  = tf.reduce_max(gauss_x * gauss_y)
    return gauss_x * gauss_y / Z_norm

#def gaussian_dist_1d(grid_x, mu_x=0.0, stddev=1.0):
#    gauss_c = 1.0 / (stddev * np.sqrt(2 * np.pi))
#    gauss_x = np.exp(np.divide(
#        -1.0*np.square(grid_x-mu_x), 2*stddev**2))
#    
#    dist_unnorm = gauss_c * gauss_x
#    Z_normalise = tf.reduce_max(dist_unnorm)
#    return dist_unnorm / Z_normalise

#def gaussian_dist_2d(
#    grid_x, grid_y, mu_x=0.0, mu_y=0.0, stddev=1.0):
#    gauss_c = 1.0 / (stddev * np.sqrt(2 * np.pi))
#    gauss_x = np.exp(np.divide(
#        -1.0*np.square(grid_x-mu_x), 2*stddev**2))
#    gauss_y = np.exp(np.divide(
#        -1.0*np.square(grid_y-mu_y), 2*stddev**2))
#    
#    dist_unnorm = gauss_x * gauss_y * (gauss_c**2)
#    Z_normalise = tf.reduce_max(dist_unnorm)
#    return dist_unnorm / Z_normalise

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
            "conv3_block4_out", "conv4_block6_out", "conv5_block3_out"]
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
    p4_residual = tf.add(
        p4_1x1,  layers.UpSampling2D(
            size=(2, 2), name="ups_P5")(p5_1x1))
    p3_residual = tf.add(
        p3_1x1, layers.UpSampling2D(
            size=(2, 2), name="ups_P4")(p4_residual))
    feature_out =  layers.Conv2D(
        256, 3, 1, "same", name="output")(p3_residual)
    
    # Output Layers. #
    layer_cls_output = feature_out
    for n_layer in range(4):
        layer_cls_output = \
            cls_cnn[n_layer](layer_cls_output)
    
    c_relu_out = tf.nn.relu(layer_cls_output)
    cls_output = layers.Conv2D(
        num_classes+1, 3, 1, 
        bias_initializer=b_focal, 
        padding="same", name="cls_output")(c_relu_out)
    
    layer_reg_output = feature_out
    for n_layer in range(4):
        layer_reg_output = \
            reg_cnn[n_layer](layer_reg_output)
    
    r_relu_out = tf.nn.relu(layer_reg_output)
    reg_output = layers.Conv2D(
        4, 3, 1, padding="same", 
        use_bias=True, name="reg_output")(r_relu_out)
    
    x_output = tf.concat([reg_output, cls_output], axis=3)
    return tf.keras.Model(
        inputs=backbone.input, outputs=x_output)

def prediction_to_corners(xy_pred, stride):
    feat_dims  = [tf.shape(xy_pred)[0], 
                  tf.shape(xy_pred)[1]]
    bbox_shape = [int(xy_pred.shape[0]), 
                  int(xy_pred.shape[1]), 4]
    bbox_coord = np.zeros(bbox_shape)
    
    ch = tf.range(0., tf.cast(
        feat_dims[0], tf.float32), dtype=tf.float32) + 0.5
    cw = tf.range(0., tf.cast(
        feat_dims[1], tf.float32), dtype=tf.float32) + 0.5
    [grid_x, grid_y] = tf.meshgrid(cw, ch)
    
    pred_x_low = grid_x - xy_pred[..., 2]
    pred_x_upp = grid_x + xy_pred[..., 3]
    pred_y_low = grid_y - xy_pred[..., 0]
    pred_y_upp = grid_y + xy_pred[..., 1]
    
    bbox_coord[:, :, 0] = pred_y_low
    bbox_coord[:, :, 2] = pred_y_upp
    bbox_coord[:, :, 1] = pred_x_low
    bbox_coord[:, :, 3] = pred_x_upp
    return stride*bbox_coord

def format_data(
    gt_labels, img_dim, num_classes, 
    img_pad=None, stride=8, sigma=0.25):
    """
    gt_labels: Normalised Gound Truth Bounding Boxes (y, x, h, w).
    """
    if img_pad is None:
        img_pad = img_dim
    
    gt_height = gt_labels[:, 2]*img_dim[0]
    gt_width  = gt_labels[:, 3]*img_dim[1]
    gt_height = gt_height.numpy()
    gt_width  = gt_width.numpy()
    
    h_ratio = img_dim[0] / stride
    w_ratio = img_dim[1] / stride
    tmp_output = np.zeros([
        int(img_pad[0] / stride), 
        int(img_pad[1] / stride), num_classes+5])
    
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
    
    tmp_labels = gt_labels.numpy()
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
        tmp_coord = [
            (tmp_label[0] - 0.5*tmp_label[2])*img_dim[0], 
            (tmp_label[1] - 0.5*tmp_label[3])*img_dim[1], 
            (tmp_label[0] + 0.5*tmp_label[2])*img_dim[0], 
            (tmp_label[1] + 0.5*tmp_label[3])*img_dim[1]]
        
        tmp_area = \
            tmp_label[2] * tmp_label[3] * h_ratio * w_ratio
        tmp_std  = tf.maximum(1.0, tf.math.sqrt(tmp_area))
        tmp_std  = 8.0
        tmp_y_cen = int(tmp_label[0] * h_ratio)
        tmp_x_cen = int(tmp_label[1] * w_ratio)
        
        tmp_y_low = 1 + int(
            (tmp_label[0]-sigma*tmp_label[2]/2) * h_ratio)
        tmp_x_low = 1 + int(
            (tmp_label[1]-sigma*tmp_label[3]/2) * w_ratio)
        tmp_y_upp = 1 + int(
            (tmp_label[0]+sigma*tmp_label[2]/2) * h_ratio)
        tmp_x_upp = 1 + int(
            (tmp_label[1]+sigma*tmp_label[3]/2) * w_ratio)
        
        tmp_y_low = max(0, tmp_y_low)
        tmp_x_low = max(0, tmp_x_low)
        tmp_y_upp = min(tmp_y_upp, int(img_dim[0] / stride))
        tmp_x_upp = min(tmp_x_upp, int(img_dim[1] / stride))
        idx_class = 5 + int(tmp_label[4])
        
        if (tmp_y_upp - tmp_y_low) > 0 \
            and (tmp_x_upp - tmp_x_low) > 0:
            tmp_y_coord = [
                float(z) + 0.5 for z in range(tmp_y_low, tmp_y_upp)]
            tmp_x_coord = [
                float(z) + 0.5 for z in range(tmp_x_low, tmp_x_upp)]
            [grid_x, grid_y] = np.meshgrid(tmp_x_coord, tmp_y_coord)
            
            tmp_output[
                tmp_y_low:tmp_y_upp, 
                tmp_x_low:tmp_x_upp, 0] = \
                    np.maximum(0, grid_y - tmp_coord[0]/stride)
            tmp_output[
                tmp_y_low:tmp_y_upp, 
                tmp_x_low:tmp_x_upp, 1] = \
                    np.maximum(0, tmp_coord[2]/stride - grid_y)
            
            tmp_output[
                tmp_y_low:tmp_y_upp, 
                tmp_x_low:tmp_x_upp, 2] = \
                    np.maximum(0, grid_x - tmp_coord[1]/stride)
            tmp_output[
                tmp_y_low:tmp_y_upp, 
                tmp_x_low:tmp_x_upp, 3] = \
                    np.maximum(0, tmp_coord[3]/stride - grid_x)
            
            new_x_cen  = int(0.5*(tmp_x_low + tmp_x_upp))
            new_y_cen  = int(0.5*(tmp_y_low + tmp_y_upp))
            tmp_center = center_dist_2d(
                grid_x, grid_y, mu_x=new_x_cen, 
                mu_y=new_y_cen, spread=tmp_std)
            
            tmp_output[
                tmp_y_low:tmp_y_upp, 
                tmp_x_low:tmp_x_upp, 4] = tmp_center
            tmp_output[
                new_y_cen, new_x_cen, 4] = 1.0
            tmp_output[
                tmp_y_low:tmp_y_upp, 
                tmp_x_low:tmp_x_upp, idx_class] = 1
        elif (tmp_y_upp - tmp_y_low) > 0 \
            and (tmp_x_upp - tmp_x_low) <= 0:
            tmp_y_coord = np.array([
                float(z) + 0.5 for z in range(tmp_y_low, tmp_y_upp)])
            
            tmp_output[
                tmp_y_low:tmp_y_upp, tmp_x_cen, 0] = \
                    np.maximum(0, tmp_y_coord - tmp_coord[0]/stride)
            tmp_output[
                tmp_y_low:tmp_y_upp, tmp_x_cen, 1] = \
                    np.maximum(0, tmp_coord[2]/stride - tmp_y_coord)
            
            tmp_output[
                tmp_y_low:tmp_y_upp, tmp_x_cen, 2] = np.maximum(
                    0, tmp_x_cen + 0.5 - tmp_coord[1]/stride)
            tmp_output[
                tmp_y_low:tmp_y_upp, tmp_x_cen, 3] = np.maximum(
                    0, tmp_coord[3]/stride - tmp_x_cen - 0.5)
            
            new_y_cen  = int(0.5*(tmp_y_low + tmp_y_upp))
            tmp_center = center_dist_1d(
                tmp_y_coord, mu_x=new_y_cen, spread=tmp_std)
            
            tmp_output[
                tmp_y_low:tmp_y_upp, tmp_x_cen, 4] = tmp_center
            tmp_output[new_y_cen, tmp_x_cen, 4] = 1.0
            tmp_output[
                tmp_y_low:tmp_y_upp, tmp_x_cen, idx_class] = 1
        elif (tmp_y_upp - tmp_y_low) <= 0 \
            and (tmp_x_upp - tmp_x_low) > 0:
            tmp_x_coord = np.array([
                float(z) + 0.5 for z in range(tmp_x_low, tmp_x_upp)])
            
            tmp_output[
                tmp_y_cen, tmp_x_low:tmp_x_upp, 0] = np.maximum(
                    0, tmp_y_cen + 0.5 - tmp_coord[0]/stride)
            tmp_output[
                tmp_y_cen, tmp_x_low:tmp_x_upp, 1] = np.maximum(
                    0, tmp_coord[2]/stride - tmp_y_cen - 0.5)
            
            tmp_output[
                tmp_y_cen, tmp_x_low:tmp_x_upp, 2] = \
                    np.maximum(0, tmp_x_coord - tmp_coord[1]/stride)
            tmp_output[
                tmp_y_cen, tmp_x_low:tmp_x_upp, 3] = \
                    np.maximum(0, tmp_coord[3]/stride - tmp_x_coord)
            
            new_x_cen  = int(0.5*(tmp_x_low + tmp_x_upp))
            tmp_center = center_dist_1d(
                tmp_x_coord, mu_x=new_x_cen, spread=tmp_std)
            
            tmp_output[
                tmp_y_cen, 
                tmp_x_low:tmp_x_upp, 4] = tmp_center
            tmp_output[tmp_y_cen, new_x_cen, 4] = 1.0
            tmp_output[
                tmp_y_cen, tmp_x_low:tmp_x_upp, idx_class] = 1
        else:
            tmp_output[
                tmp_y_cen, tmp_x_cen, 0] = np.maximum(
                    0, tmp_y_cen + 0.5 - tmp_coord[0]/stride)
            tmp_output[
                tmp_y_cen, tmp_x_cen, 1] = np.maximum(
                    0, tmp_coord[2]/stride - tmp_y_cen - 0.5)
            
            tmp_output[
                tmp_y_cen, tmp_x_cen, 2] = np.maximum(
                    0, tmp_x_cen + 0.5 - tmp_coord[1]/stride)
            tmp_output[
                tmp_y_cen, tmp_x_cen, 3] = np.maximum(
                    0, tmp_coord[3]/stride - tmp_x_cen - 0.5)
            
            tmp_output[
                tmp_y_cen, tmp_x_cen, 4] = 1
            tmp_output[
                tmp_y_cen, tmp_x_cen, idx_class] = 1
    return tmp_output

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

def iou_loss(xy_true, xy_pred, mask):
    """
    Intersection over Union (IoU) Loss Function.
    Note that the coordinates are scaled by the stride of the feature map.
    """
    # Generate the grid of centroids. #
    feat_dims = [tf.shape(xy_pred)[0], 
                 tf.shape(xy_pred)[1]]
    
    h = tf.range(0., tf.cast(
        feat_dims[0], tf.float32), dtype=tf.float32)
    w = tf.range(0., tf.cast(
        feat_dims[1], tf.float32), dtype=tf.float32)
    [grid_x, grid_y] = tf.meshgrid(w, h)
    
    true_x_low = grid_x - xy_true[..., 2]
    true_x_upp = grid_x + xy_true[..., 3]
    true_y_low = grid_y - xy_true[..., 0]
    true_y_upp = grid_y + xy_true[..., 1]
    
    pred_x_low = grid_x - xy_pred[..., 2]
    pred_x_upp = grid_x + xy_pred[..., 3]
    pred_y_low = grid_y - xy_pred[..., 0]
    pred_y_upp = grid_y + xy_pred[..., 1]
    
    true_box_dim = [
        true_y_upp - true_y_low, 
        true_x_upp - true_x_low]
    pred_box_dim = [
        pred_y_upp - pred_y_low, 
        pred_x_upp - pred_x_low]
    
    inter_height = tf.maximum(0, tf.subtract(
        tf.minimum(true_y_upp, pred_y_upp), 
        tf.maximum(true_y_low, pred_y_low)))
    inter_width  = tf.maximum(0, tf.subtract(
        tf.minimum(true_x_upp, pred_x_upp), 
        tf.maximum(true_x_low, pred_x_low)))
    
    inter_area = inter_width * inter_height
    union_area = tf.add(
        true_box_dim[0]*true_box_dim[1], 
        pred_box_dim[0]*pred_box_dim[1])
    union_area = union_area - inter_area
    
    iou = inter_area / (union_area + 1.0e-12)
    tot_iou_loss = tf.reduce_sum(
        -1.0 * tf.math.log(iou + 1.0e-12) * mask)
    return tot_iou_loss

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

def model_loss(
    y_true, y_pred, reg_type="l1", cen_type="l1"):
    """
    y_true: Normalised Gound Truth Bounding Boxes (x, y, w, h).
    """
    tmp_obj  = tf.reduce_max(
        y_true[..., 5:], axis=-1)
    tmp_mask = tf.cast(tmp_obj >= 1, tf.float32)
    
    cls_loss = focal_loss(
        y_true[..., 5:], y_pred[0][..., 5:])
    
    if cen_type.lower() == "l1":
        cen_loss = smooth_l1_loss(
            y_true[..., 4], tf.nn.sigmoid(
            y_pred[0][..., 4]), mask=1.0)
    
    if reg_type.lower() == "iou":
        reg_loss = iou_loss(
            y_true[..., :4], 
            y_pred[0][..., :4], tmp_mask)
    else:
        reg_loss = smooth_l1_loss(
            y_true[..., :4], 
            y_pred[0][..., :4], mask=tmp_mask)
    return cls_loss, reg_loss, cen_loss

    
